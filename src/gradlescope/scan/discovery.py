"""Module discovery and full-repository scanning."""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from gradlescope.model import BuildFile, Module, Repo, VersionCatalog
from gradlescope.scan import parser

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


def detect_languages(directory: str) -> set:
    langs = set()
    src = os.path.join(directory, "src")
    if not os.path.isdir(src):
        return langs
    for dirpath, _dirs, files in os.walk(src):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            lang = _SOURCE_EXTENSIONS.get(ext)
            if lang:
                langs.add(lang)
    return langs


def _build_file_for(directory: str) -> Optional[BuildFile]:
    path = _first_existing(directory, _BUILD_FILES)
    if path is None:
        return None
    return BuildFile(path=path, text=_read(path))


def _load_module(root: str, gradle_path: str, catalog_plugins: Dict[str, str]) -> Module:
    directory = gradle_path_to_dir(root, gradle_path)
    build_file = _build_file_for(directory)
    plugins = []
    dependencies = []
    if build_file is not None:
        plugins = parser.parse_plugins(build_file.text, catalog_plugins=catalog_plugins)
        dependencies = parser.parse_dependencies(build_file.text)
    return Module(
        path=gradle_path,
        directory=directory,
        build_file=build_file,
        plugins=plugins,
        dependencies=dependencies,
        languages=detect_languages(directory),
    )


def _discover_via_filesystem(root: str) -> List[str]:
    """Fallback when there is no settings file: find module directories."""
    paths: List[str] = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS and not d.startswith(".")]
        if dirpath == root:
            continue
        if any(f in _BUILD_FILES for f in files):
            rel = os.path.relpath(dirpath, root)
            paths.append(":" + rel.replace(os.sep, ":"))
    return sorted(paths)


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
    settings_path = _first_existing(root, _SETTINGS_FILES)
    if settings_path is not None:
        includes = parser.parse_settings_includes(_read(settings_path))
    else:
        includes = _discover_via_filesystem(root)
    # A single-module project (root build script, no subprojects) is still a
    # Gradle project — model the root itself as module ":" so it is not lost.
    if not includes and _build_file_for(root) is not None:
        includes = [":"]
    return [_load_module(root, path, catalog_plugins) for path in includes]


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
    )
