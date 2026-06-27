"""Tests for plugin classification and overview."""
from gradlescope.analysis.plugins import classify_plugin, plugin_overview
from gradlescope.model import Module, Plugin, Repo


class TestClassify:
    def test_core(self):
        assert classify_plugin("java", False, set()) == "core"
        assert classify_plugin("org.gradle.something", False, set()) == "core"

    def test_convention(self):
        assert classify_plugin("myorg.java-conventions", False, {"myorg.java-conventions"}) == "convention"

    def test_external_by_prefix(self):
        assert classify_plugin("org.springframework.boot", False, set()) == "external"

    def test_external_by_version(self):
        assert classify_plugin("com.example.thing", True, set()) == "external"

    def test_internal(self):
        assert classify_plugin("com.acme.internal.service", False, set()) == "internal"

    def test_toolchains_resolver_is_external_not_core(self):
        assert classify_plugin("org.gradle.toolchains.foojay-resolver-convention", False, set()) == "external"


class TestOverview:
    def test_overview_counts_and_categories(self):
        a = Module(
            path=":a",
            directory="/r/a",
            plugins=[Plugin(id="java"), Plugin(id="org.springframework.boot", version="3.2.0")],
        )
        b = Module(
            path=":b",
            directory="/r/b",
            plugins=[Plugin(id="java"), Plugin(id="myorg.java-conventions")],
        )
        repo = Repo(root="/r", modules=[a, b], convention_plugin_ids={"myorg.java-conventions"})
        ov = plugin_overview(repo)
        assert ov["distinct"] == 3
        by_id = {p["id"]: p for p in ov["plugins"]}
        assert by_id["java"]["count"] == 2 and by_id["java"]["category"] == "core"
        assert by_id["org.springframework.boot"]["category"] == "external"
        assert by_id["myorg.java-conventions"]["category"] == "convention"
        assert ov["category_counts"]["external"] == 1

    def test_version_conflict_detected(self):
        a = Module(path=":a", directory="/r/a", plugins=[Plugin(id="org.springframework.boot", version="2.7.0")])
        b = Module(path=":b", directory="/r/b", plugins=[Plugin(id="org.springframework.boot", version="3.2.0")])
        repo = Repo(root="/r", modules=[a, b])
        ov = plugin_overview(repo)
        boot = next(p for p in ov["plugins"] if p["id"] == "org.springframework.boot")
        assert boot["version_conflict"] is True
        assert set(boot["versions"]) == {"2.7.0", "3.2.0"}
        assert ov["version_conflicts"] == 1
