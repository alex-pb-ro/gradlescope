"""Heuristic parsers for Gradle build scripts, settings, properties, catalogs.

These are intentionally regex/heuristic based rather than full Groovy/Kotlin
parsers: the goal is to be fast and robust across thousands of modules and to
degrade gracefully on syntax we do not understand. Each function is pure
(text in, data out) so it is trivially unit-testable.
"""
from __future__ import annotations

import re
import textwrap
import tomllib
from typing import Dict, List, Optional

from gradlescope.model import Dependency, Plugin, VersionCatalog

# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #


def strip_comments(text: str) -> str:
    """Remove ``/* */`` and ``//`` comments while preserving string literals.

    String-literal awareness means ``//`` inside a quoted URL (``"https://..."``)
    is kept, and braces/comment markers inside strings are not misread.
    """
    out: List[str] = []
    i, n = 0, len(text)
    quote = None
    while i < n:
        ch = text[i]
        if quote is not None:
            out.append(ch)
            if ch == quote and text[i - 1] != "\\":
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = end + 2 if end != -1 else n
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            i = end if end != -1 else n
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def extract_blocks(text: str, name: str) -> List[str]:
    """Return the inner content of every ``name { ... }`` block.

    Comments are stripped first, and brace matching is string-literal aware so a
    ``{``/``}`` inside a quoted value does not open/close a block spuriously.
    """
    text = strip_comments(text)
    blocks: List[str] = []
    pattern = re.compile(r"\b" + re.escape(name) + r"\s*\{")
    for match in pattern.finditer(text):
        depth = 1
        i = match.end()
        start = i
        quote = None
        while i < len(text) and depth > 0:
            ch = text[i]
            if quote is not None:
                if ch == quote and text[i - 1] != "\\":
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        blocks.append(text[start : i - 1])
    return blocks


def _iter_statements(block: str):
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "/*", "*", "#")):
            continue
        yield line


# --------------------------------------------------------------------------- #
# Plugins
# --------------------------------------------------------------------------- #

_VERSION_RE = re.compile(r"\bversion\s*(?:\(\s*)?(['\"])(.+?)\1")
_APPLY_FALSE_RE = re.compile(r"\bapply\s*(?:=\s*|\(\s*)?false\b")
_ID_RE = re.compile(r"\bid\s*(?:\(\s*)?(['\"])(.+?)\1")
_KOTLIN_RE = re.compile(r"\bkotlin\s*\(\s*(['\"])(.+?)\1")
_ALIAS_RE = re.compile(r"\balias\s*\(\s*([\w.]+)\s*\)")
_SHORTHAND_RE = re.compile(r"`?([A-Za-z][\w.\-]*)`?$")
_APPLY_PLUGIN_GROOVY_RE = re.compile(r"apply\s+plugin\s*:\s*(['\"])(.+?)\1")
_APPLY_PLUGIN_KOTLIN_RE = re.compile(r"apply\s*\(\s*plugin\s*=\s*(['\"])(.+?)\1")


def _find_version(line: str) -> Optional[str]:
    m = _VERSION_RE.search(line)
    return m.group(2) if m else None


def _has_apply_false(line: str) -> bool:
    return bool(_APPLY_FALSE_RE.search(line))


def _parse_plugin_line(line: str, catalog_plugins: Optional[Dict[str, str]]):
    m = _ID_RE.search(line)
    if m:
        return Plugin(m.group(2), _find_version(line), not _has_apply_false(line))
    m = _KOTLIN_RE.search(line)
    if m:
        return Plugin(
            "org.jetbrains.kotlin." + m.group(2),
            _find_version(line),
            not _has_apply_false(line),
        )
    m = _ALIAS_RE.search(line)
    if m and catalog_plugins:
        key = m.group(1).split(".plugins.", 1)[-1]
        resolved = catalog_plugins.get(key) or catalog_plugins.get(key.replace(".", "-"))
        if resolved:
            return Plugin(resolved, _find_version(line), not _has_apply_false(line))
        return None
    m = _SHORTHAND_RE.fullmatch(line)
    if m:
        return Plugin(m.group(1), None, True)
    return None


def parse_plugins(text: str, catalog_plugins: Optional[Dict[str, str]] = None) -> List[Plugin]:
    """Parse plugin declarations from a build script."""
    found: List[Plugin] = []
    seen: set = set()

    def add(plugin: Optional[Plugin]) -> None:
        if plugin and plugin.id not in seen:
            seen.add(plugin.id)
            found.append(plugin)

    for block in extract_blocks(text, "plugins"):
        for line in _iter_statements(block):
            add(_parse_plugin_line(line, catalog_plugins))

    clean = strip_comments(text)
    for m in _APPLY_PLUGIN_GROOVY_RE.finditer(clean):
        add(Plugin(m.group(2)))
    for m in _APPLY_PLUGIN_KOTLIN_RE.finditer(clean):
        add(Plugin(m.group(2)))

    return found


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #

_CONFIG_RE = re.compile(r"^([A-Za-z][\w]*)\b")
_PROJECT_RE = re.compile(r"\bproject\s*\(\s*(['\"])(.+?)\1")
_PLATFORM_RE = re.compile(r"\b(?:enforcedPlatform|platform)\s*\(\s*(['\"])(.+?)\1")
_COORD_RE = re.compile(r"(['\"])([^\"':]+:[^\"':]+(?::[^'\"]+)?)\1")
_CATALOG_RE = re.compile(r"\blibs\.[A-Za-z][\w.]*")
_MAP_GROUP_RE = re.compile(r"\bgroup\s*:\s*(['\"])(.+?)\1")
_MAP_NAME_RE = re.compile(r"\bname\s*:\s*(['\"])(.+?)\1")
_MAP_VERSION_RE = re.compile(r"\bversion\s*:\s*(['\"])(.+?)\1")

_CONFIG_SUFFIXES = ("Implementation", "Api", "CompileOnly", "RuntimeOnly", "AnnotationProcessor")
_CONFIG_EXACT = {
    "implementation",
    "api",
    "compileOnly",
    "compileOnlyApi",
    "runtimeOnly",
    "annotationProcessor",
    "kapt",
    "ksp",
    "developmentOnly",
    "testFixturesApi",
    "testFixturesImplementation",
}


def _is_dep_config(name: str) -> bool:
    return name in _CONFIG_EXACT or name.endswith(_CONFIG_SUFFIXES)


def _parse_dependency_line(line: str) -> Optional[Dependency]:
    cfg_match = _CONFIG_RE.match(line)
    if not cfg_match:
        return None
    config = cfg_match.group(1)
    if not _is_dep_config(config):
        return None

    m = _PROJECT_RE.search(line)
    if m:
        return Dependency(configuration=config, project_path=m.group(2))

    m = _PLATFORM_RE.search(line)
    if m:
        return Dependency(configuration=config, raw=m.group(2))

    g = _MAP_GROUP_RE.search(line)
    n = _MAP_NAME_RE.search(line)
    if g and n:
        v = _MAP_VERSION_RE.search(line)
        raw = f"{g.group(2)}:{n.group(2)}"
        if v:
            raw += f":{v.group(2)}"
        return Dependency(configuration=config, raw=raw)

    m = _COORD_RE.search(line)
    if m:
        return Dependency(configuration=config, raw=m.group(2))

    if _CATALOG_RE.search(line):
        return Dependency(configuration=config, raw="")

    return None


def parse_dependencies(text: str) -> List[Dependency]:
    """Parse dependency declarations from a build script."""
    deps: List[Dependency] = []
    for block in extract_blocks(text, "dependencies"):
        for line in _iter_statements(block):
            dep = _parse_dependency_line(line)
            if dep is not None:
                deps.append(dep)
    return deps


# --------------------------------------------------------------------------- #
# gradle.properties / settings / wrapper / catalogs
# --------------------------------------------------------------------------- #


def parse_gradle_properties(text: str) -> Dict[str, str]:
    props: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


_INCLUDE_LINE_RE = re.compile(r"^\s*include\b(?!Build)")
_QUOTED_RE = re.compile(r"(['\"])(.+?)\1")
_ROOT_NAME_RE = re.compile(r"rootProject\.name\s*=\s*(['\"])(.+?)\1")
_WRAPPER_RE = re.compile(r"gradle-(\d+(?:\.\d+)+)-(?:bin|all)\.zip")


def parse_settings_includes(text: str) -> List[str]:
    includes: List[str] = []
    for raw in text.splitlines():
        if not _INCLUDE_LINE_RE.match(raw):
            continue
        for _, value in _QUOTED_RE.findall(raw):
            path = value if value.startswith(":") else ":" + value
            includes.append(path)
    return includes


def parse_root_project_name(text: str) -> Optional[str]:
    m = _ROOT_NAME_RE.search(text)
    return m.group(2) if m else None


def parse_wrapper_version(text: str) -> Optional[str]:
    m = _WRAPPER_RE.search(text)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# JVM / language versions
# --------------------------------------------------------------------------- #

_TOOLCHAIN_RE = re.compile(r"languageVersion\s*(?:=|\.set\()\s*JavaLanguageVersion\.of\(\s*(\d+)\s*\)")
_KOTLIN_TOOLCHAIN_RE = re.compile(r"jvmToolchain\(\s*(?:JavaLanguageVersion\.of\(\s*)?(\d+)")
_KOTLIN_JVMTARGET_RE = re.compile(
    r"jvmTarget\s*(?:=|\.set\()\s*(?:JvmTarget\.JVM_)?['\"]?(\d+(?:[._]\d+)?)['\"]?"
)
_SOURCE_COMPAT_RE = re.compile(r"sourceCompatibility\s*=?\s*(.+)")
_TARGET_COMPAT_RE = re.compile(r"targetCompatibility\s*=?\s*(.+)")
_JAVA_VERSION_TOKEN_RE = re.compile(r"VERSION_(\d+)(?:_(\d+))?|['\"](\d+(?:\.\d+)?)['\"]|toVersion\(\s*['\"]?(\d+(?:\.\d+)?)")


def _norm_java_version(raw: Optional[str]) -> Optional[str]:
    """Normalize a Java version token to a major-version string.

    Examples: "1.8"->"8", "VERSION_1_8"->"8", "VERSION_17"->"17", "11.0"->"11",
    "JVM_1_8" (passed as "1_8")->"8".
    """
    if not raw:
        return None
    s = raw.strip()
    m = _JAVA_VERSION_TOKEN_RE.search(s)
    if not m:
        bare = re.search(r"(\d+(?:[._]\d+)?)", s)
        if not bare:
            return None
        val = bare.group(1)
    elif m.group(1):  # VERSION_X[_Y]
        major, minor = m.group(1), m.group(2)
        val = f"{major}.{minor}" if minor else major
    else:
        val = m.group(3) or m.group(4)
    val = val.replace("_", ".")
    if "." in val:
        head, tail = val.split(".", 1)
        # Old "1.x" form -> x ; modern "11.0"-style -> major only.
        return tail if head == "1" else head
    return val


def parse_jvm_versions(text: str) -> Dict[str, Optional[str]]:
    """Best-effort extraction of a module's Java/Kotlin version configuration."""
    text = strip_comments(text)
    toolchain = None
    m = _TOOLCHAIN_RE.search(text)
    if m:
        toolchain = m.group(1)
    kotlin = None
    m = _KOTLIN_TOOLCHAIN_RE.search(text)
    if m:
        kotlin = m.group(1)
    else:
        m = _KOTLIN_JVMTARGET_RE.search(text)
        if m:
            kotlin = _norm_java_version(m.group(1))

    source = None
    m = _SOURCE_COMPAT_RE.search(text)
    if m:
        source = _norm_java_version(m.group(1))
    target = None
    m = _TARGET_COMPAT_RE.search(text)
    if m:
        target = _norm_java_version(m.group(1))

    return {
        "jvm_toolchain": toolchain,
        "kotlin_jvm": kotlin,
        "source_compat": source,
        "target_compat": target,
    }


def _coord_from_table_entry(entry) -> Optional[str]:
    """Return ``group:name[:version]`` from a TOML library/plugin entry."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        if "module" in entry:
            module = entry["module"]
            version = entry.get("version")
            if isinstance(version, str):
                return f"{module}:{version}"
            return module
        if "group" in entry and "name" in entry:
            coord = f"{entry['group']}:{entry['name']}"
            version = entry.get("version")
            if isinstance(version, str):
                coord += f":{version}"
            return coord
    return None


def parse_version_catalog(text: str, name: str = "libs") -> VersionCatalog:
    data = tomllib.loads(textwrap.dedent(text))
    versions = {k: str(v) for k, v in data.get("versions", {}).items()}

    libraries: Dict[str, str] = {}
    for key, entry in data.get("libraries", {}).items():
        coord = _coord_from_table_entry(entry)
        if coord is not None:
            libraries[key] = coord

    plugins: Dict[str, str] = {}
    for key, entry in data.get("plugins", {}).items():
        if isinstance(entry, dict) and "id" in entry:
            plugins[key] = entry["id"]
        elif isinstance(entry, str):
            plugins[key] = entry.split(":", 1)[0]

    bundles = {k: list(v) for k, v in data.get("bundles", {}).items()}

    return VersionCatalog(
        name=name,
        versions=versions,
        libraries=libraries,
        plugins=plugins,
        bundles=bundles,
    )
