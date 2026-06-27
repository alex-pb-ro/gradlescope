"""Plugin classification and project-wide plugin overview.

Classifies each applied plugin as:

- ``core``       — a Gradle built-in plugin
- ``convention`` — defined in this repo's buildSrc/build-logic (in-house shared config)
- ``external``   — resolved from a public/managed plugin repository
- ``internal``   — an in-house plugin not detected as a convention plugin
"""
from __future__ import annotations

from typing import Dict, Iterable, Set

from gradlescope.model import Repo

CORE_PLUGINS: Set[str] = {
    "java",
    "java-library",
    "java-platform",
    "application",
    "groovy",
    "scala",
    "war",
    "base",
    "distribution",
    "maven-publish",
    "ivy-publish",
    "signing",
    "jacoco",
    "checkstyle",
    "pmd",
    "codenarc",
    "idea",
    "eclipse",
    "project-report",
    "version-catalog",
    "antlr",
    "jvm-test-suite",
    "test-report-aggregation",
}

# Namespaces published to public plugin repositories.
EXTERNAL_PREFIXES = (
    "org.springframework",
    "org.jetbrains.kotlin",
    "org.jetbrains.intellij",
    "io.spring",
    "com.android",
    "com.github",
    "com.google",
    "com.diffplug",
    "org.flywaydb",
    "com.bmuschko",
    "io.gitlab.arturbosch.detekt",
    "org.sonarqube",
    "com.gradle",
    "org.openapi",
    "io.freefair",
    "org.gradle.toolchains",
    "nebula",
    "com.netflix",
)


def classify_plugin(plugin_id: str, has_version: bool, convention_ids: Set[str]) -> str:
    if plugin_id in convention_ids:
        return "convention"
    # The foojay toolchains resolver lives under org.gradle.* but ships from the
    # plugin portal — classify it as external before the broad core check.
    if plugin_id.startswith("org.gradle.toolchains"):
        return "external"
    if plugin_id in CORE_PLUGINS or plugin_id.startswith("org.gradle"):
        return "core"
    if has_version or plugin_id.startswith(EXTERNAL_PREFIXES):
        return "external"
    if "." in plugin_id:
        return "internal"
    # Bare, unversioned, unknown name — most likely a core plugin alias.
    return "core"


def plugin_overview(repo: Repo) -> Dict:
    convention_ids = repo.convention_plugin_ids or set()
    usage: Dict[str, Dict] = {}
    for module in repo.modules:
        for plugin in module.plugins:
            entry = usage.setdefault(
                plugin.id, {"id": plugin.id, "count": 0, "applied": 0, "versions": set(), "modules": []}
            )
            entry["count"] += 1
            entry["modules"].append(module.path)
            if plugin.applied:
                entry["applied"] += 1
            if plugin.version:
                entry["versions"].add(plugin.version)

    plugins = []
    category_counts: Dict[str, int] = {"core": 0, "convention": 0, "external": 0, "internal": 0}
    for pid, entry in usage.items():
        versions = sorted(entry["versions"])
        category = classify_plugin(pid, bool(versions), convention_ids)
        category_counts[category] = category_counts.get(category, 0) + 1
        plugins.append(
            {
                "id": pid,
                "category": category,
                "count": entry["count"],
                "applied": entry["applied"],
                "versions": versions,
                "version_conflict": len(versions) > 1,
                "modules": sorted(entry["modules"]),
            }
        )
    plugins.sort(key=lambda p: (-p["count"], p["id"]))
    return {
        "distinct": len(plugins),
        "category_counts": category_counts,
        "version_conflicts": sum(1 for p in plugins if p["version_conflict"]),
        "plugins": plugins,
    }


def category_color(category: str) -> str:
    return {
        "core": "#64748b",
        "convention": "#16a34a",
        "external": "#4f7cff",
        "internal": "#d97706",
    }.get(category, "#64748b")


def _ids(plugins: Iterable[Dict]) -> Set[str]:  # pragma: no cover - convenience
    return {p["id"] for p in plugins}
