"""Core data model for gradlescope.

These are plain, dependency-free dataclasses describing what we discover in a
Gradle repository. Parsing/discovery logic lives in :mod:`gradlescope.scan`;
this module only holds the data and a handful of pure convenience accessors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Set


class Severity(IntEnum):
    """Ordered severity levels. Higher is worse."""

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def from_name(cls, name: str) -> "Severity":
        try:
            return cls[name.strip().upper()]
        except KeyError as exc:  # pragma: no cover - exercised via test
            raise ValueError(f"Unknown severity: {name!r}") from exc

    @property
    def label(self) -> str:
        return self.name.capitalize()


_LATEST_MARKERS = ("latest.", "latest-")


@dataclass(frozen=True)
class Dependency:
    """A single declared dependency.

    ``raw`` holds the external notation ``group:name:version`` (when known).
    For project dependencies, ``project_path`` is set instead.
    """

    configuration: str
    raw: str = ""
    project_path: Optional[str] = None

    @property
    def is_project(self) -> bool:
        return self.project_path is not None

    @property
    def _parts(self) -> List[str]:
        return self.raw.split(":") if self.raw else []

    @property
    def group(self) -> Optional[str]:
        parts = self._parts
        return parts[0] if len(parts) >= 1 and parts[0] else None

    @property
    def name(self) -> Optional[str]:
        parts = self._parts
        return parts[1] if len(parts) >= 2 and parts[1] else None

    @property
    def version(self) -> Optional[str]:
        parts = self._parts
        return parts[2] if len(parts) >= 3 and parts[2] else None

    @property
    def is_dynamic(self) -> bool:
        v = self.version
        if not v:
            return False
        v_lower = v.lower()
        if any(marker in v_lower for marker in _LATEST_MARKERS):
            return True
        # Gradle dynamic suffixes: "+", "1.+", "1.2.+" (a trailing '+'). A '+'
        # elsewhere is semver build metadata (e.g. "1.0.0+build.5"), not dynamic.
        if v.endswith("+"):
            return True
        # Maven-style version ranges: "[1.0,2.0)", "(,1.0]", etc.
        if ("[" in v or "(" in v) and ("]" in v or ")" in v) and "," in v:
            return True
        return False

    @property
    def is_snapshot(self) -> bool:
        v = self.version
        return bool(v) and v.upper().endswith("-SNAPSHOT")


@dataclass(frozen=True)
class Plugin:
    """A Gradle plugin application."""

    id: str
    version: Optional[str] = None
    applied: bool = True

    @property
    def is_spring_boot(self) -> bool:
        return self.id == "org.springframework.boot"


@dataclass
class BuildFile:
    """A build script file and its raw contents."""

    path: str
    text: str = ""

    @property
    def is_kotlin(self) -> bool:
        return self.path.endswith(".kts")

    @property
    def language(self) -> str:
        return "kotlin" if self.is_kotlin else "groovy"


@dataclass
class Module:
    """A Gradle subproject (module)."""

    path: str
    directory: str
    build_file: Optional[BuildFile] = None
    plugins: List[Plugin] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    languages: Set[str] = field(default_factory=set)
    properties: Dict[str, str] = field(default_factory=dict)
    type_count: int = 0
    abstract_type_count: int = 0
    jvm_toolchain: Optional[str] = None
    kotlin_jvm: Optional[str] = None
    source_compat: Optional[str] = None
    target_compat: Optional[str] = None

    @property
    def name(self) -> str:
        if self.path in ("", ":"):
            return ":"
        return self.path.rsplit(":", 1)[-1]

    def has_plugin(self, plugin_id: str) -> bool:
        return any(p.id == plugin_id for p in self.plugins)

    @property
    def project_dependencies(self) -> List[Dependency]:
        return [d for d in self.dependencies if d.is_project]

    @property
    def compat_target(self) -> Optional[str]:
        """The bytecode/compatibility target, if declared (target wins over source)."""
        return self.target_compat or self.source_compat

    @property
    def jvm_version(self) -> Optional[str]:
        """Best single Java/JVM version for display."""
        return self.jvm_toolchain or self.kotlin_jvm or self.compat_target

    @property
    def runs_compat(self) -> bool:
        """True if the module targets an older Java than its toolchain (compat mode)."""
        compat = self.compat_target
        if not compat:
            return False
        if self.jvm_toolchain is None:
            return True  # compat set without a toolchain -> relies on machine JDK
        try:
            return int(compat) < int(self.jvm_toolchain)
        except ValueError:  # pragma: no cover - non-numeric versions
            return False


@dataclass
class VersionCatalog:
    """A Gradle version catalog (e.g. ``gradle/libs.versions.toml``)."""

    name: str = "libs"
    versions: Dict[str, str] = field(default_factory=dict)
    libraries: Dict[str, str] = field(default_factory=dict)
    plugins: Dict[str, str] = field(default_factory=dict)
    bundles: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class Repo:
    """Everything discovered about a scanned Gradle repository."""

    root: str
    modules: List[Module] = field(default_factory=list)
    settings_file: Optional[str] = None
    settings_text: str = ""
    root_build_file: Optional[BuildFile] = None
    gradle_properties: Dict[str, str] = field(default_factory=dict)
    version_catalogs: List[VersionCatalog] = field(default_factory=list)
    gradle_version: Optional[str] = None
    convention_plugin_ids: Set[str] = field(default_factory=set)

    def module_by_path(self, path: str) -> Optional[Module]:
        for m in self.modules:
            if m.path == path:
                return m
        return None

    @property
    def module_count(self) -> int:
        return len(self.modules)

    def plugin_ids(self) -> Set[str]:
        ids: Set[str] = set()
        for m in self.modules:
            for p in m.plugins:
                ids.add(p.id)
        return ids


@dataclass
class Finding:
    """A single issue raised by a rule.

    A finding with ``module_path is None`` is repo-level (applies to the whole
    build). ``weight`` feeds the scoring engine; ``runbook`` links to a runbook.
    """

    rule_id: str
    title: str
    severity: Severity
    category: str
    message: str
    recommendation: str = ""
    module_path: Optional[str] = None
    weight: int = 1
    runbook: Optional[str] = None
    evidence: Optional[str] = None

    @property
    def is_repo_level(self) -> bool:
        return self.module_path is None

    @property
    def key(self) -> str:
        """Stable identifier for a finding (rule + scope)."""
        return f"{self.rule_id}@{self.module_path or '-'}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity.name,
            "category": self.category,
            "message": self.message,
            "recommendation": self.recommendation,
            "module_path": self.module_path,
            "weight": self.weight,
            "runbook": self.runbook,
            "evidence": self.evidence,
        }
