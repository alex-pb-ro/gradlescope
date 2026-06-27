"""Tests for the core data model."""
import pytest

from gradlescope.model import (
    BuildFile,
    Dependency,
    Finding,
    Module,
    Plugin,
    Repo,
    Severity,
    VersionCatalog,
)


class TestSeverity:
    def test_ordering(self):
        assert Severity.INFO < Severity.LOW < Severity.MEDIUM
        assert Severity.MEDIUM < Severity.HIGH < Severity.CRITICAL

    def test_from_name_case_insensitive(self):
        assert Severity.from_name("high") is Severity.HIGH
        assert Severity.from_name("CRITICAL") is Severity.CRITICAL

    def test_from_name_invalid(self):
        with pytest.raises(ValueError):
            Severity.from_name("bogus")

    def test_label(self):
        assert Severity.HIGH.label == "High"


class TestDependency:
    def test_external_dependency_parts(self):
        dep = Dependency(configuration="implementation", raw="com.google.guava:guava:32.0")
        assert dep.group == "com.google.guava"
        assert dep.name == "guava"
        assert dep.version == "32.0"
        assert dep.is_project is False
        assert dep.is_dynamic is False

    def test_project_dependency(self):
        dep = Dependency(configuration="api", raw="", project_path=":core:utils")
        assert dep.is_project is True
        assert dep.project_path == ":core:utils"

    def test_dynamic_version_plus(self):
        dep = Dependency(configuration="implementation", raw="org.foo:bar:1.+")
        assert dep.is_dynamic is True

    def test_dynamic_version_latest(self):
        dep = Dependency(configuration="implementation", raw="org.foo:bar:latest.release")
        assert dep.is_dynamic is True

    def test_snapshot_version(self):
        dep = Dependency(configuration="implementation", raw="org.foo:bar:1.0-SNAPSHOT")
        assert dep.is_snapshot is True

    def test_no_version_not_dynamic(self):
        dep = Dependency(configuration="implementation", raw="org.foo:bar")
        assert dep.version is None
        assert dep.is_dynamic is False


class TestPlugin:
    def test_defaults_applied(self):
        p = Plugin(id="java")
        assert p.applied is True
        assert p.version is None

    def test_is_spring_boot(self):
        assert Plugin(id="org.springframework.boot").is_spring_boot is True
        assert Plugin(id="java").is_spring_boot is False


class TestBuildFile:
    def test_kotlin_detection(self):
        bf = BuildFile(path="/r/build.gradle.kts", text="plugins {}")
        assert bf.is_kotlin is True
        assert bf.language == "kotlin"

    def test_groovy_detection(self):
        bf = BuildFile(path="/r/build.gradle", text="plugins {}")
        assert bf.is_kotlin is False
        assert bf.language == "groovy"


class TestModule:
    def test_name_from_path(self):
        m = Module(path=":core:utils", directory="/r/core/utils")
        assert m.name == "utils"

    def test_root_module_name(self):
        m = Module(path=":", directory="/r")
        assert m.name == ":"

    def test_has_plugin(self):
        m = Module(path=":a", directory="/r/a", plugins=[Plugin(id="java")])
        assert m.has_plugin("java") is True
        assert m.has_plugin("kotlin") is False

    def test_project_dependencies(self):
        deps = [
            Dependency(configuration="api", raw="", project_path=":b"),
            Dependency(configuration="implementation", raw="g:a:1"),
        ]
        m = Module(path=":a", directory="/r/a", dependencies=deps)
        assert [d.project_path for d in m.project_dependencies] == [":b"]

    def test_languages_default_empty(self):
        m = Module(path=":a", directory="/r/a")
        assert m.languages == set()


class TestVersionCatalog:
    def test_lookup(self):
        cat = VersionCatalog(
            name="libs",
            versions={"guava": "32.0"},
            libraries={"guava": "com.google.guava:guava"},
            plugins={"boot": "org.springframework.boot"},
            bundles={"web": ["guava"]},
        )
        assert cat.versions["guava"] == "32.0"
        assert "guava" in cat.libraries


class TestRepo:
    def test_module_by_path(self):
        a = Module(path=":a", directory="/r/a")
        repo = Repo(root="/r", modules=[a])
        assert repo.module_by_path(":a") is a
        assert repo.module_by_path(":missing") is None

    def test_module_count(self):
        repo = Repo(root="/r", modules=[Module(path=":a", directory="/r/a")])
        assert repo.module_count == 1

    def test_all_plugins_ids(self):
        a = Module(path=":a", directory="/r/a", plugins=[Plugin(id="java")])
        b = Module(path=":b", directory="/r/b", plugins=[Plugin(id="java"), Plugin(id="kotlin")])
        repo = Repo(root="/r", modules=[a, b])
        assert repo.plugin_ids() == {"java", "kotlin"}


class TestFinding:
    def test_to_dict_roundtrips_core_fields(self):
        f = Finding(
            rule_id="config-cache-disabled",
            title="Configuration cache not enabled",
            severity=Severity.HIGH,
            category="configuration-cache",
            message="msg",
            recommendation="enable it",
            module_path=":a",
            weight=10,
            runbook="configuration-cache",
        )
        d = f.to_dict()
        assert d["rule_id"] == "config-cache-disabled"
        assert d["severity"] == "HIGH"
        assert d["module_path"] == ":a"
        assert d["weight"] == 10

    def test_repo_level_finding_has_no_module(self):
        f = Finding(
            rule_id="r",
            title="t",
            severity=Severity.LOW,
            category="c",
            message="m",
            recommendation="rec",
        )
        assert f.module_path is None
        assert f.is_repo_level is True
