"""Regression tests for issues found by the adversarial code review."""
import os

import pytest

from gradlescope import cli
from gradlescope.analysis.rule import RuleContext
from gradlescope.analysis.rules import dependencies, structure
from gradlescope.dashboard import charts
from gradlescope.dashboard.runbooks import render_markdown
from gradlescope.graph.depgraph import DependencyGraph
from gradlescope.model import BuildFile, Dependency, Module, Plugin, Repo
from gradlescope.scan import parser, scan_repo
from gradlescope.server.app import is_valid_task


def _ctx(repo, config=None):
    return RuleContext(repo=repo, graph=DependencyGraph.from_repo(repo), config=config or {})


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# --- parser: comment handling (#1, #2) ------------------------------------- #
class TestParserComments:
    def test_commented_apply_plugin_ignored(self):
        text = "// apply plugin: 'commented-out'\napply plugin: 'real'\n"
        ids = {p.id for p in parser.parse_plugins(text)}
        assert ids == {"real"}

    def test_inline_comment_does_not_corrupt_version(self):
        text = "plugins {\n id 'java' // version '9.9.9' was here\n}\n"
        plugins = parser.parse_plugins(text)
        assert plugins[0].id == "java"
        assert plugins[0].version is None

    def test_inline_comment_does_not_flip_apply_false(self):
        text = "plugins {\n id 'x' version '1' // apply false note\n}\n"
        assert parser.parse_plugins(text)[0].applied is True

    def test_url_in_string_not_treated_as_comment(self):
        # `//` inside a quoted URL must survive comment stripping.
        assert "https://repo.example.com" in parser.strip_comments("url 'https://repo.example.com' // c")

    def test_unterminated_block_comment_stripped_to_end(self):
        assert parser.strip_comments("a /* never closed").rstrip() == "a"

    def test_line_comment_to_eof(self):
        assert parser.strip_comments("a // tail").rstrip() == "a"


# --- parser: brace inside strings (#4) ------------------------------------- #
class TestParserBraces:
    def test_brace_inside_quoted_string_does_not_truncate_block(self):
        # The `}` is INSIDE a quoted string; string-aware brace matching must
        # not treat it as the end of the dependencies block.
        text = 'dependencies {\n implementation "weird}name:x:1"\n implementation "g:b:2"\n}\n'
        raws = {d.raw for d in parser.parse_dependencies(text)}
        assert "g:b:2" in raws  # the second dep survives only if the block didn't close early
        assert len(raws) == 2

    def test_open_brace_in_string_does_not_extend_block(self):
        # A `{` inside a string must not inflate brace depth and swallow a later block.
        text = (
            'dependencies {\n implementation "g:a:{1}"\n}\n'
            'somethingElse {\n implementation "should:not:parse"\n}\n'
        )
        raws = {d.raw for d in parser.parse_dependencies(text)}
        assert raws == {"g:a:{1}"}


# --- parser: version catalog version preserved (#3) ------------------------ #
class TestCatalogVersion:
    def test_group_name_version_form_keeps_version(self):
        toml = '[libraries]\na = { group = "g", name = "n", version = "1.2.3" }\n'
        cat = parser.parse_version_catalog(toml)
        assert cat.libraries["a"] == "g:n:1.2.3"


# --- discovery: single-module repo (#5) ------------------------------------ #
class TestSingleModule:
    def test_root_only_repo_yields_root_module(self, tmp_path):
        root = str(tmp_path)
        _write(os.path.join(root, "settings.gradle"), "rootProject.name = 'solo'\n")
        _write(os.path.join(root, "build.gradle"), "plugins { id 'java' }\n")
        repo = scan_repo(root)
        assert repo.module_by_path(":") is not None
        assert repo.module_count == 1


# --- model: is_dynamic precision (#11, #23) -------------------------------- #
class TestIsDynamic:
    def test_build_metadata_not_dynamic(self):
        assert Dependency("implementation", raw="g:a:1.0.0+build.5").is_dynamic is False

    def test_trailing_plus_is_dynamic(self):
        assert Dependency("implementation", raw="g:a:1.+").is_dynamic is True

    def test_range_is_dynamic(self):
        assert Dependency("implementation", raw="g:a:[1.0,2.0)").is_dynamic is True


# --- rules: apply(from=...) and toolchain scoping (#7, #8, #9, #10) -------- #
class TestRuleFixes:
    def test_kotlin_apply_from_detected(self):
        repo = Repo(
            root="/r",
            root_build_file=BuildFile(path="/r/build.gradle.kts", text='apply(from = "x.gradle.kts")'),
        )
        findings = structure.ApplyFromScriptPlugin().evaluate(_ctx(repo))
        assert findings and findings[0].is_repo_level

    def test_root_only_toolchain_does_not_cover_subprojects(self):
        # toolchain is root-only; subprojects block has no toolchain -> still flagged.
        m = Module(path=":a", directory="/r/a", plugins=[Plugin(id="java")],
                   build_file=BuildFile(path="/r/a/build.gradle", text="plugins{}"))
        repo = Repo(
            root="/r",
            modules=[m],
            root_build_file=BuildFile(
                path="/r/build.gradle",
                text="java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }\n"
                     "subprojects { repositories { mavenCentral() } }",
            ),
        )
        assert structure.MissingJavaToolchain().evaluate(_ctx(repo))

    def test_toolchain_inside_subprojects_covers(self):
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

    def test_global_skip_recognizes_non_literal_toolchain_marker(self):
        # A subprojects block whose only signal is sourceCompatibility (no literal
        # "toolchain") must still count as global coverage.
        m = Module(path=":a", directory="/r/a", plugins=[Plugin(id="java")],
                   build_file=BuildFile(path="/r/a/build.gradle", text="plugins{}"))
        repo = Repo(
            root="/r",
            modules=[m],
            root_build_file=BuildFile(
                path="/r/build.gradle",
                text="subprojects { sourceCompatibility = JavaVersion.VERSION_21 }",
            ),
        )
        assert structure.MissingJavaToolchain().evaluate(_ctx(repo)) == []

    def test_commented_mavenlocal_not_flagged(self):
        m = Module(path=":a", directory="/r/a",
                   build_file=BuildFile(path="/r/a/build.gradle", text="// mavenLocal()"))
        repo = Repo(root="/r", modules=[m])
        assert dependencies.MavenLocalUsed().evaluate(_ctx(repo)) == []

    def test_commented_root_mavenlocal_not_flagged(self):
        repo = Repo(
            root="/r",
            root_build_file=BuildFile(path="/r/build.gradle", text="repositories {\n // mavenLocal()\n mavenCentral()\n}"),
        )
        assert dependencies.MavenLocalUsed().evaluate(_ctx(repo)) == []

    def test_commented_apply_from_not_flagged(self):
        repo = Repo(root="/r", root_build_file=BuildFile(path="/r/build.gradle", text="// apply from: 'x.gradle'"))
        assert structure.ApplyFromScriptPlugin().evaluate(_ctx(repo)) == []

    def test_commented_cross_project_not_flagged(self):
        repo = Repo(root="/r", root_build_file=BuildFile(path="/r/build.gradle", text="// subprojects { }"))
        assert structure.CrossProjectConfiguration().evaluate(_ctx(repo)) == []


# --- dashboard: link XSS + donut single slice (#12, #13, #14, #22) -------- #
class TestDashboardSecurity:
    def test_javascript_link_neutralized(self):
        out = render_markdown("[click](javascript:alert(1))")
        assert 'href="javascript:' not in out

    def test_data_link_neutralized(self):
        out = render_markdown("[x](data:text/html,<script>alert(1)</script>)")
        assert 'href="data:' not in out

    def test_safe_link_preserved(self):
        out = render_markdown("[ok](https://example.com)")
        assert '<a href="https://example.com"' in out

    def test_donut_single_full_slice_renders_ring(self):
        svg = charts.donut_chart([("only", 5, "#f00"), ("zero", 0, "#0f0")])
        assert svg.count('class="slice"') == 1
        assert "<circle" in svg  # full ring, not a degenerate arc path


# --- server: task flag allowlist (#16) ------------------------------------- #
class TestServerTaskValidation:
    def test_dangerous_flags_rejected(self):
        assert not is_valid_task("--init-script evil.gradle")
        assert not is_valid_task("--include-build ../x")
        assert not is_valid_task("-b other.gradle")

    def test_safe_flags_allowed(self):
        assert is_valid_task("--dry-run build")
        assert is_valid_task(":app:test --info")


# --- server: dispatch hardening (#17) -------------------------------------- #
class TestServerDispatch:
    def _serve(self, tmp_path):
        import threading

        from gradlescope.server.app import build_server

        root = str(tmp_path)
        _write(os.path.join(root, "settings.gradle"), "include ':a'\n")
        _write(os.path.join(root, "a", "build.gradle"), "plugins{}")
        httpd = build_server(root, "127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd

    def test_malformed_content_length_does_not_crash(self, tmp_path):
        import http.client

        httpd = self._serve(tmp_path)
        try:
            port = httpd.server_address[1]
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.putrequest("GET", "/api/status")
            conn.putheader("Content-Length", "not-a-number")
            conn.endheaders()
            resp = conn.getresponse()
            assert resp.status == 200
            resp.read()
        finally:
            httpd.shutdown()

    def test_handler_exception_becomes_500(self, tmp_path):
        import http.client

        httpd = self._serve(tmp_path)
        try:
            def boom(*_a, **_k):
                raise RuntimeError("kaboom")

            httpd.gradlescope_server.handle = boom
            port = httpd.server_address[1]
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request("GET", "/")
            resp = conn.getresponse()
            assert resp.status == 500
            assert b"Internal error" in resp.read()
        finally:
            httpd.shutdown()


# --- packaging (#20) ------------------------------------------------------- #
def test_pyproject_package_data_excludes_missing_assets():
    import tomllib

    path = os.path.join(os.path.dirname(__file__), os.pardir, "pyproject.toml")
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    globs = data["tool"]["setuptools"]["package-data"]["gradlescope"]
    assert "runbooks/*.md" in globs
    assert not any("assets" in g for g in globs)


# --- cli: config error handling (#18, #19) --------------------------------- #
class TestCliConfigErrors:
    def test_missing_config_file(self, tmp_path):
        _write(os.path.join(str(tmp_path), "settings.gradle"), "include ':a'\n")
        _write(os.path.join(str(tmp_path), "a", "build.gradle"), "plugins{}")
        with pytest.raises(SystemExit):
            cli.main(["score", "--root", str(tmp_path), "--config", str(tmp_path / "nope.json")])

    def test_invalid_json_config(self, tmp_path):
        cfg = tmp_path / "bad.json"
        cfg.write_text("{ not json", encoding="utf-8")
        with pytest.raises(SystemExit):
            cli.main(["score", "--root", str(tmp_path), "--config", str(cfg)])
