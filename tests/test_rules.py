"""Tests for the rule engine and built-in rules."""
from gradlescope.analysis import analyze
from gradlescope.analysis.rule import RuleContext, all_rules, run_rules
from gradlescope.analysis.rules import caching, dependencies, structure
from gradlescope.graph.depgraph import DependencyGraph
from gradlescope.model import BuildFile, Dependency, Module, Plugin, Repo, VersionCatalog


def _ctx(repo, config=None):
    return RuleContext(repo=repo, graph=DependencyGraph.from_repo(repo), config=config or {})


def _ids(findings):
    return {f.rule_id for f in findings}


class TestRegistry:
    def test_all_rules_registered(self):
        ids = {r.id for r in all_rules()}
        # A representative sampling across categories.
        for expected in [
            "config-cache-disabled",
            "build-cache-disabled",
            "parallel-disabled",
            "no-version-catalog",
            "dynamic-versions",
            "cross-project-configuration",
            "dependency-cycles",
            "missing-java-toolchain",
        ]:
            assert expected in ids

    def test_run_rules_sorted_by_severity_desc(self):
        repo = Repo(root="/r")  # bare repo trips many repo-level rules
        findings = run_rules(_ctx(repo))
        severities = [int(f.severity) for f in findings]
        assert severities == sorted(severities, reverse=True)


class TestCachingRules:
    def test_config_cache_disabled_when_absent(self):
        repo = Repo(root="/r")
        assert "config-cache-disabled" in _ids(caching.ConfigurationCacheDisabled().evaluate(_ctx(repo)))

    def test_config_cache_ok_when_enabled(self):
        repo = Repo(root="/r", gradle_properties={"org.gradle.configuration-cache": "true"})
        assert caching.ConfigurationCacheDisabled().evaluate(_ctx(repo)) == []

    def test_config_cache_unsafe_variant_accepted(self):
        repo = Repo(root="/r", gradle_properties={"org.gradle.unsafe.configuration-cache": "true"})
        assert caching.ConfigurationCacheDisabled().evaluate(_ctx(repo)) == []

    def test_build_cache_disabled(self):
        repo = Repo(root="/r")
        assert caching.BuildCacheDisabled().evaluate(_ctx(repo))
        repo2 = Repo(root="/r", gradle_properties={"org.gradle.caching": "true"})
        assert caching.BuildCacheDisabled().evaluate(_ctx(repo2)) == []

    def test_parallel_disabled(self):
        assert caching.ParallelExecutionDisabled().evaluate(_ctx(Repo(root="/r")))

    def test_cc_incompatible_plugin_denylist(self):
        m = Module(path=":a", directory="/r/a", plugins=[Plugin(id="com.bad.plugin")])
        repo = Repo(root="/r", modules=[m])
        rule = caching.ConfigCacheIncompatiblePlugin()
        # No denylist configured -> no findings.
        assert rule.evaluate(_ctx(repo)) == []
        # With the plugin on the denylist -> flagged.
        findings = rule.evaluate(_ctx(repo, {"cc_incompatible_plugins": ["com.bad.plugin"]}))
        assert findings and findings[0].module_path == ":a"

    def test_remote_cache_missing_and_present(self):
        assert caching.RemoteBuildCacheMissing().evaluate(_ctx(Repo(root="/r")))
        repo = Repo(root="/r", settings_text="buildCache { remote(HttpBuildCache) { url = '...' } }")
        assert caching.RemoteBuildCacheMissing().evaluate(_ctx(repo)) == []


class TestDependencyRules:
    def test_no_version_catalog(self):
        assert dependencies.NoVersionCatalog().evaluate(_ctx(Repo(root="/r")))
        repo = Repo(root="/r", version_catalogs=[VersionCatalog(name="libs")])
        assert dependencies.NoVersionCatalog().evaluate(_ctx(repo)) == []

    def test_dynamic_versions(self):
        m = Module(
            path=":a",
            directory="/r/a",
            dependencies=[Dependency(configuration="implementation", raw="g:a:1.+")],
        )
        findings = dependencies.DynamicVersions().evaluate(_ctx(Repo(root="/r", modules=[m])))
        assert findings and findings[0].module_path == ":a"

    def test_snapshot_versions(self):
        m = Module(
            path=":a",
            directory="/r/a",
            dependencies=[Dependency(configuration="implementation", raw="g:a:1.0-SNAPSHOT")],
        )
        findings = dependencies.SnapshotVersions().evaluate(_ctx(Repo(root="/r", modules=[m])))
        assert findings and findings[0].module_path == ":a"

    def test_maven_local_in_root_and_module(self):
        m = Module(
            path=":a",
            directory="/r/a",
            build_file=BuildFile(path="/r/a/build.gradle", text="repositories { mavenLocal() }"),
        )
        repo = Repo(
            root="/r",
            modules=[m],
            root_build_file=BuildFile(path="/r/build.gradle", text="repositories { mavenLocal() }"),
        )
        findings = dependencies.MavenLocalUsed().evaluate(_ctx(repo))
        assert len(findings) == 2
        assert any(f.is_repo_level for f in findings)
        assert any(f.module_path == ":a" for f in findings)


class TestStructureRules:
    def test_cross_project_configuration(self):
        repo = Repo(
            root="/r",
            root_build_file=BuildFile(path="/r/build.gradle", text="subprojects { apply plugin: 'java' }"),
        )
        findings = structure.CrossProjectConfiguration().evaluate(_ctx(repo))
        assert findings and findings[0].evidence == "subprojects"

    def test_cross_project_clean(self):
        repo = Repo(root="/r", root_build_file=BuildFile(path="/r/build.gradle", text="plugins { id 'base' }"))
        assert structure.CrossProjectConfiguration().evaluate(_ctx(repo)) == []

    def test_dependency_cycles(self):
        a = Module(path=":a", directory="/r/a", dependencies=[Dependency("implementation", project_path=":b")])
        b = Module(path=":b", directory="/r/b", dependencies=[Dependency("implementation", project_path=":a")])
        findings = structure.DependencyCycles().evaluate(_ctx(Repo(root="/r", modules=[a, b])))
        assert findings and "->" in findings[0].evidence

    def test_excessive_depth_threshold(self):
        # chain of 4 modules, custom threshold of 2 -> flagged
        mods = []
        for i, nxt in [(0, 1), (1, 2), (2, 3), (3, None)]:
            deps = [Dependency("implementation", project_path=f":m{nxt}")] if nxt is not None else []
            mods.append(Module(path=f":m{i}", directory=f"/r/m{i}", dependencies=deps))
        repo = Repo(root="/r", modules=mods)
        findings = structure.ExcessiveGraphDepth().evaluate(_ctx(repo, {"max_graph_depth": 2}))
        assert findings

    def test_high_fan_in(self):
        mods = [Module(path=":hub", directory="/r/hub")]
        for i in range(3):
            mods.append(
                Module(path=f":c{i}", directory=f"/r/c{i}", dependencies=[Dependency("implementation", project_path=":hub")])
            )
        repo = Repo(root="/r", modules=mods)
        findings = structure.HighFanInHub().evaluate(_ctx(repo, {"max_fan_in": 2}))
        assert findings and findings[0].module_path == ":hub"

    def test_high_fan_out(self):
        targets = [Module(path=f":t{i}", directory=f"/r/t{i}") for i in range(3)]
        hub = Module(
            path=":h",
            directory="/r/h",
            dependencies=[Dependency("implementation", project_path=f":t{i}") for i in range(3)],
        )
        repo = Repo(root="/r", modules=[hub, *targets])
        findings = structure.HighFanOut().evaluate(_ctx(repo, {"max_fan_out": 2}))
        assert findings and findings[0].module_path == ":h"

    def test_outdated_gradle(self):
        assert structure.OutdatedGradle().evaluate(_ctx(Repo(root="/r", gradle_version="6.9")))
        assert structure.OutdatedGradle().evaluate(_ctx(Repo(root="/r", gradle_version="8.6"))) == []

    def test_unknown_gradle_version(self):
        findings = structure.OutdatedGradle().evaluate(_ctx(Repo(root="/r", gradle_version=None)))
        assert findings and findings[0].severity.name == "LOW"

    def test_missing_java_toolchain(self):
        m = Module(
            path=":a",
            directory="/r/a",
            plugins=[Plugin(id="java")],
            build_file=BuildFile(path="/r/a/build.gradle", text="plugins { id 'java' }"),
        )
        findings = structure.MissingJavaToolchain().evaluate(_ctx(Repo(root="/r", modules=[m])))
        assert findings and findings[0].module_path == ":a"

    def test_toolchain_present_no_finding(self):
        m = Module(
            path=":a",
            directory="/r/a",
            plugins=[Plugin(id="java")],
            build_file=BuildFile(
                path="/r/a/build.gradle",
                text="java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }",
            ),
        )
        assert structure.MissingJavaToolchain().evaluate(_ctx(Repo(root="/r", modules=[m]))) == []

    def test_global_toolchain_in_root_skips_modules(self):
        m = Module(path=":a", directory="/r/a", plugins=[Plugin(id="java")],
                   build_file=BuildFile(path="/r/a/build.gradle", text="plugins{}"))
        repo = Repo(
            root="/r",
            modules=[m],
            root_build_file=BuildFile(
                path="/r/build.gradle",
                text="subprojects { java { toolchain { languageVersion = JavaLanguageVersion.of(21) } } }",
            ),
        )
        assert structure.MissingJavaToolchain().evaluate(_ctx(repo)) == []


def test_analyze_end_to_end_returns_findings():
    m = Module(
        path=":a",
        directory="/r/a",
        plugins=[Plugin(id="java")],
        dependencies=[Dependency("implementation", raw="g:a:1.+")],
        build_file=BuildFile(path="/r/a/build.gradle", text="plugins { id 'java' }"),
    )
    repo = Repo(root="/r", modules=[m])
    findings = analyze(repo)
    ids = _ids(findings)
    assert "config-cache-disabled" in ids
    assert "dynamic-versions" in ids
    assert "missing-java-toolchain" in ids
