"""Module discovery and full-repository scanning."""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from gradlescope.model import BuildFile, Module, Repo, VersionCatalog
from gradlescope.scan import parser

# Heuristic type-declaration detection for abstractness (Clean Architecture A).
_TYPE_RE = re.compile(r"\b(class|interface|enum|object|record)\s+[A-Za-z_]")
_ABSTRACT_RE = re.compile(
    r"(\binterface\s+[A-Za-z_]|\babstract\s+(class|fun class)\s+[A-Za-z_]"
    r"|\bsealed\s+(class|interface)\s+[A-Za-z_]|@interface\s+[A-Za-z_])"
)
_TYPE_EXTENSIONS = {".java", ".kt"}
_MAX_SOURCE_BYTES = 400_000

_SETTINGS_FILES = ("settings.gradle.kts", "settings.gradle")
_BUILD_FILES = ("build.gradle.kts", "build.gradle")
_SOURCE_EXTENSIONS = {
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".py": "python",
    ".sh": "shell",
    ".bash": "shell",
    ".groovy": "groovy",
    ".scala": "scala",
}
_IGNORED_DIRS = {".git", ".gradle", "build", "node_modules", ".idea", "out", ".venv"}
# Directories that are separate builds, not subprojects of the main build.
_DISCOVERY_IGNORED_DIRS = _IGNORED_DIRS | {"buildSrc", "build-logic", "gradle"}
_MAX_LANG_FILES = 20000


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:  # pragma: no cover - defensive
        return ""


def _first_existing(directory: str, names) -> Optional[str]:
    for name in names:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def gradle_path_to_dir(root: str, gradle_path: str) -> str:
    segments = [s for s in gradle_path.split(":") if s]
    return os.path.join(root, *segments)


def _count_types_in_file(path: str) -> Tuple[int, int]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read(_MAX_SOURCE_BYTES)
    except OSError:  # pragma: no cover - defensive
        return 0, 0
    return len(_TYPE_RE.findall(text)), len(_ABSTRACT_RE.findall(text))


def scan_sources(directory: str) -> Tuple[set, int, int]:
    """Walk a module's own sources, returning (languages, type_count,
    abstract_type_count).

    Scans the whole subtree (not just ``src/``) but prunes ignored dirs and
    nested module boundaries so a parent never absorbs a child module.
    """
    langs: set = set()
    total_types = 0
    abstract_types = 0
    if not os.path.isdir(directory):
        return langs, 0, 0
    budget = _MAX_LANG_FILES
    for dirpath, dirnames, files in os.walk(directory):
        kept = []
        for d in dirnames:
            if d in _DISCOVERY_IGNORED_DIRS or d.startswith("."):
                continue
            if _first_existing(os.path.join(dirpath, d), _BUILD_FILES) is not None:
                continue  # nested module boundary
            kept.append(d)
        dirnames[:] = kept
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            lang = _SOURCE_EXTENSIONS.get(ext)
            if lang:
                langs.add(lang)
            if ext in _TYPE_EXTENSIONS:
                t, a = _count_types_in_file(os.path.join(dirpath, name))
                total_types += t
                abstract_types += a
            budget -= 1
            if budget <= 0:
                return langs, total_types, abstract_types
    return langs, total_types, abstract_types


def detect_languages(directory: str) -> set:
    """Detect source languages in a module (languages only; see scan_sources)."""
    return scan_sources(directory)[0]


def _build_file_for(directory: str) -> Optional[BuildFile]:
    path = _first_existing(directory, _BUILD_FILES)
    if path is None:
        return None
    return BuildFile(path=path, text=_read(path))


def _load_module(
    root: str,
    gradle_path: str,
    catalog_plugins: Dict[str, str],
    directory: Optional[str] = None,
) -> Module:
    directory = directory or gradle_path_to_dir(root, gradle_path)
    build_file = _build_file_for(directory)
    plugins = []
    dependencies = []
    if build_file is not None:
        plugins = parser.parse_plugins(build_file.text, catalog_plugins=catalog_plugins)
        dependencies = parser.parse_dependencies(build_file.text)
    languages, type_count, abstract_count = scan_sources(directory)
    return Module(
        path=gradle_path,
        directory=directory,
        build_file=build_file,
        plugins=plugins,
        dependencies=dependencies,
        languages=languages,
        type_count=type_count,
        abstract_type_count=abstract_count,
    )


def _discover_via_filesystem(root: str) -> List[str]:
    """Find every directory that contains a build script (module directory).

    Used to augment ``include`` declarations so that modules added
    programmatically (globbed/looped includes that we cannot statically parse)
    are still discovered.
    """
    paths: List[str] = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in _DISCOVERY_IGNORED_DIRS and not d.startswith(".")
        ]
        if dirpath == root:
            continue
        if any(f in _BUILD_FILES for f in files):
            rel = os.path.relpath(dirpath, root)
            paths.append(":" + rel.replace(os.sep, ":"))
    return sorted(paths)


# Matches both `id = "..."` (Groovy/Kotlin property) and `id("...")` (Kotlin call).
_PLUGIN_ID_RE = re.compile(r"""\bid\s*(?:=\s*|\(\s*)['"]([^'"]+)['"]""")


def _ids_in_gradle_plugin_blocks(text: str) -> set:
    """Plugin ids registered inside ``gradlePlugin { ... }`` blocks only.

    Scoping to the block avoids matching unrelated ``id = "..."`` assignments
    (task config, custom extensions, etc.).
    """
    ids: set = set()
    for block in parser.extract_blocks(text, "gradlePlugin"):
        for m in _PLUGIN_ID_RE.finditer(block):
            ids.add(m.group(1))
    return ids


def detect_convention_plugin_ids(root: str) -> set:
    """Find plugin ids defined inside the repo (convention/in-house plugins).

    Looks in buildSrc/ and build-logic/ for precompiled script plugins
    (``*.gradle[.kts]`` files) and ids registered in ``gradlePlugin { ... }``.
    """
    ids: set = set()
    for base in ("buildSrc", "build-logic"):
        directory = os.path.join(root, base)
        if not os.path.isdir(directory):
            continue
        for dirpath, dirnames, files in os.walk(directory):
            dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS and not d.startswith(".")]
            for name in files:
                if name in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"):
                    ids |= _ids_in_gradle_plugin_blocks(_read(os.path.join(dirpath, name)))
                elif name.endswith(".gradle.kts"):
                    ids.add(name[: -len(".gradle.kts")])
                elif name.endswith(".gradle"):
                    ids.add(name[: -len(".gradle")])
    return ids


def _load_catalogs(root: str) -> List[VersionCatalog]:
    catalogs: List[VersionCatalog] = []
    gradle_dir = os.path.join(root, "gradle")
    if not os.path.isdir(gradle_dir):
        return catalogs
    for name in sorted(os.listdir(gradle_dir)):
        if name.endswith(".versions.toml"):
            stem = name[: -len(".versions.toml")]
            try:
                catalogs.append(parser.parse_version_catalog(_read(os.path.join(gradle_dir, name)), name=stem))
            except Exception:  # pragma: no cover - malformed catalog tolerated
                continue
    return catalogs


def discover_modules(root: str, catalog_plugins: Optional[Dict[str, str]] = None) -> List[Module]:
    catalog_plugins = catalog_plugins or {}
    declared: Dict[str, str] = {}  # gradle path -> directory

    settings_path = _first_existing(root, _SETTINGS_FILES)
    if settings_path is not None:
        for path in parser.parse_settings_includes(_read(settings_path)):
            declared[path] = gradle_path_to_dir(root, path)

    # Always union with a filesystem sweep: large monorepos frequently include
    # modules dynamically (e.g. globbed/looped includes) which we cannot parse
    # statically. The union ensures we do not undercount.
    for path in _discover_via_filesystem(root):
        declared.setdefault(path, gradle_path_to_dir(root, path))

    # A single-module project (root build script, no subprojects) is still a
    # Gradle project — model the root itself as module ":" so it is not lost.
    if not declared and _build_file_for(root) is not None:
        declared[":"] = root

    return [
        _load_module(root, path, catalog_plugins, directory=declared[path])
        for path in sorted(declared)
    ]


def scan_repo(root: str) -> Repo:
    """Scan a Gradle repository rooted at ``root`` into a :class:`Repo`."""
    root = os.path.abspath(root)

    settings_path = _first_existing(root, _SETTINGS_FILES)
    gradle_props_path = os.path.join(root, "gradle.properties")
    gradle_properties = (
        parser.parse_gradle_properties(_read(gradle_props_path))
        if os.path.isfile(gradle_props_path)
        else {}
    )

    catalogs = _load_catalogs(root)
    catalog_plugins: Dict[str, str] = {}
    for cat in catalogs:
        catalog_plugins.update(cat.plugins)

    root_build_file = _build_file_for(root)

    wrapper_path = os.path.join(root, "gradle", "wrapper", "gradle-wrapper.properties")
    gradle_version = parser.parse_wrapper_version(_read(wrapper_path)) if os.path.isfile(wrapper_path) else None

    modules = discover_modules(root, catalog_plugins=catalog_plugins)

    return Repo(
        root=root,
        modules=modules,
        settings_file=settings_path,
        settings_text=_read(settings_path) if settings_path else "",
        root_build_file=root_build_file,
        gradle_properties=gradle_properties,
        version_catalogs=catalogs,
        gradle_version=gradle_version,
        convention_plugin_ids=detect_convention_plugin_ids(root),
    )
