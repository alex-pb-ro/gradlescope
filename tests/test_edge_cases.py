"""Targeted edge-case tests to harden parsing, rendering, and the runner."""
import os
import sys

from gradlescope.dashboard import runbooks
from gradlescope.report import markdown_report
from gradlescope.result import build_result
from gradlescope.scan import parser
from gradlescope.server.app import DashboardServer, default_runner
from gradlescope.model import Repo, VersionCatalog


class TestParserEdges:
    def test_enforced_platform(self):
        deps = parser.parse_dependencies(
            "dependencies { implementation enforcedPlatform('g:bom:1.0') }"
        )
        assert deps[0].raw == "g:bom:1.0"

    def test_kotlin_plugin_apply_false(self):
        plugins = parser.parse_plugins('plugins { kotlin("jvm") version "1.9" apply false }')
        p = plugins[0]
        assert p.id == "org.jetbrains.kotlin.jvm"
        assert p.applied is False

    def test_alias_without_catalog_is_ignored(self):
        plugins = parser.parse_plugins("plugins { alias(libs.plugins.foo) }")
        assert plugins == []

    def test_includebuild_not_treated_as_project(self):
        includes = parser.parse_settings_includes("includeBuild 'build-logic'\ninclude ':app'\n")
        assert includes == [":app"]

    def test_map_notation_without_version(self):
        deps = parser.parse_dependencies("dependencies { implementation group: 'g', name: 'n' }")
        assert deps[0].raw == "g:n"

    def test_property_line_without_equals_ignored(self):
        props = parser.parse_gradle_properties("novalue\nk=v\n")
        assert props == {"k": "v"}

    def test_catalog_library_group_name_form(self):
        toml = """
        [libraries]
        a = { group = "g", name = "n" }
        b = { group = "g", name = "n", version = "1" }
        """
        cat = parser.parse_version_catalog(toml)
        assert cat.libraries["a"] == "g:n"
        assert cat.libraries["b"] == "g:n:1"

    def test_catalog_plugin_string_form(self):
        toml = """
        [plugins]
        p = "com.example.plugin:1.2.3"
        """
        cat = parser.parse_version_catalog(toml)
        assert cat.plugins["p"] == "com.example.plugin"

    def test_catalog_library_module_with_version(self):
        toml = """
        [libraries]
        a = { module = "g:n", version = "9" }
        """
        cat = parser.parse_version_catalog(toml)
        assert cat.libraries["a"] == "g:n:9"


class TestRunbookEdges:
    def test_blockquote_and_hr(self):
        out = runbooks.render_markdown("> quoted\n\n---\n")
        assert "<blockquote>quoted</blockquote>" in out
        assert "<hr/>" in out

    def test_switch_between_list_types(self):
        out = runbooks.render_markdown("- a\n1. b\n")
        assert "<ul>" in out and "<ol>" in out

    def test_unterminated_code_block_closes(self):
        out = runbooks.render_markdown("```\ncode")
        assert out.count("<pre><code>") == 1
        assert out.rstrip().endswith("</code></pre>")

    def test_title_fallback_when_no_h1(self, tmp_path):
        (tmp_path / "x.md").write_text("no heading here\n", encoding="utf-8")
        loaded = runbooks.load_runbooks(str(tmp_path))
        assert loaded["x"]["title"] == "x"


class TestRunnerSuccessAndFailure:
    def test_success(self):
        r = default_runner([sys.executable, "-c", "print('BUILD SUCCESSFUL')"], cwd=".")
        assert r["ok"] is True and r["returncode"] == 0
        assert "BUILD OK" in r["message"]

    def test_failure(self):
        r = default_runner([sys.executable, "-c", "import sys; sys.exit(3)"], cwd=".")
        assert r["ok"] is False and r["returncode"] == 3


class TestServerPersistenceAndBadBody:
    def _make_repo(self, root):
        os.makedirs(os.path.join(root, "app"), exist_ok=True)
        with open(os.path.join(root, "settings.gradle"), "w") as fh:
            fh.write("include ':app'\n")
        with open(os.path.join(root, "app", "build.gradle"), "w") as fh:
            fh.write("plugins { id 'java' }\n")

    def test_history_persisted_to_output_dir(self, tmp_path):
        root = str(tmp_path / "repo")
        out = str(tmp_path / "out")
        self._make_repo(root)
        DashboardServer(root=root, output_dir=out, now_fn=lambda: "t")
        assert os.path.isfile(os.path.join(out, "history.json"))

    def test_run_with_non_json_body_is_rejected(self, tmp_path):
        root = str(tmp_path / "repo")
        self._make_repo(root)
        srv = DashboardServer(root=root, runner=lambda a, c: {"ok": True}, now_fn=lambda: "t")
        status, _, _ = srv.handle("POST", "/api/run", b"not-json")
        assert status == 400


def test_markdown_report_no_findings_branch():
    # A fully-configured repo with no modules trips no rules at all.
    repo = Repo(
        root="/clean",
        modules=[],
        settings_text="buildCache { remote(HttpBuildCache) {} }",
        gradle_version="8.8",
        version_catalogs=[VersionCatalog(name="libs")],
        gradle_properties={
            "org.gradle.configuration-cache": "true",
            "org.gradle.caching": "true",
            "org.gradle.parallel": "true",
            "org.gradle.unsafe.isolated-projects": "true",
        },
    )
    result = build_result(repo, generated_at="t")
    md = markdown_report.to_markdown(result)
    assert "No issues found" in md
