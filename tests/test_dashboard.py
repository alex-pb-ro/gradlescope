"""Tests for HTML helpers, runbook rendering, and the site generator."""
import os

from gradlescope.dashboard import html, runbooks, site
from gradlescope.model import BuildFile, Dependency, Module, Plugin, Repo
from gradlescope.result import build_result


def _result():
    a = Module(
        path=":app",
        directory="/r/app",
        plugins=[Plugin(id="java")],
        languages={"java"},
        dependencies=[Dependency("implementation", project_path=":core"), Dependency("implementation", raw="g:a:1.+")],
        build_file=BuildFile(path="/r/app/build.gradle", text="plugins { id 'java' }\napply from: 'x.gradle'"),
    )
    core = Module(path=":core", directory="/r/core", plugins=[Plugin(id="java-library")], languages={"kotlin"})
    repo = Repo(root="/r", modules=[a, core], gradle_version="7.2")
    return build_result(repo, generated_at="2026-01-01T00:00")


class TestHtmlHelpers:
    def test_page_structure_and_nav(self):
        out = html.page("Title", "<p>hi</p>", "findings.html")
        assert out.startswith("<!DOCTYPE html>")
        assert 'href="findings.html" class="active"' in out
        assert "<p>hi</p>" in out

    def test_escaping(self):
        assert "&lt;script&gt;" in html.stat("<script>", "x")

    def test_table_renders_rows(self):
        t = html.table(["A", "B"], [["1", "2"], ["3", "4"]])
        assert t.count("<tr>") == 3  # header + 2 rows
        assert "<th>A</th>" in t

    def test_live_toolbar_only_when_live(self):
        assert "gsRescan()" in html.page("t", "b", "index.html", live=True)
        assert "gsRescan()" not in html.page("t", "b", "index.html", live=False)

    def test_grade_and_sev_badges(self):
        assert "grade-A" in html.grade_badge("A")
        assert "sev-HIGH" in html.sev_badge("HIGH")


class TestRunbookRendering:
    def test_headings_lists_code_inline(self):
        md = "# Title\n\nSome **bold** and `code`.\n\n- one\n- two\n\n```\nx=1\n```\n"
        out = runbooks.render_markdown(md)
        assert "<h1>Title</h1>" in out
        assert "<strong>bold</strong>" in out
        assert "<code>code</code>" in out
        assert "<ul>" in out and out.count("<li>") == 2
        assert "<pre><code>" in out

    def test_links_and_ordered_list(self):
        md = "1. first\n2. second\n\n[docs](https://example.com)\n"
        out = runbooks.render_markdown(md)
        assert "<ol>" in out
        assert '<a href="https://example.com"' in out

    def test_code_block_escaped(self):
        out = runbooks.render_markdown("```\n<tag>\n```")
        assert "&lt;tag&gt;" in out

    def test_load_runbooks_from_dir(self, tmp_path):
        (tmp_path / "demo.md").write_text("# Demo\n\nbody\n", encoding="utf-8")
        loaded = runbooks.load_runbooks(str(tmp_path))
        assert "demo" in loaded
        assert loaded["demo"]["title"] == "Demo"
        assert "<p>body</p>" in loaded["demo"]["html"]

    def test_load_missing_dir(self):
        assert runbooks.load_runbooks("/no/such/dir") == {}


class TestSite:
    def test_build_pages_returns_all_pages(self):
        pages = site.build_pages(_result())
        for name in [
            "index.html", "findings.html", "modules.html", "graph.html",
            "architecture.html", "plugins.html", "processes.html", "runbooks.html", "ai.html",
        ]:
            assert name in pages
            assert pages[name].startswith("<!DOCTYPE html>")

    def test_index_has_gauge_and_charts(self):
        pages = site.build_pages(_result())
        idx = pages["index.html"]
        assert "gauge" in idx
        assert "donut-chart" in idx
        assert "hbar-chart" in idx

    def test_findings_page_filterable_with_prompt_buttons(self):
        pages = site.build_pages(_result())
        f = pages["findings.html"]
        assert "data-row" in f
        assert "gsFilter()" in f
        assert "gsCopyPrompt(" in f
        assert "GS_PROMPTS" in f

    def test_graph_page_has_canvas(self):
        pages = site.build_pages(_result())
        assert "gv-canvas" in pages["graph.html"]

    def test_architecture_page_has_scatter(self):
        pages = site.build_pages(_result())
        assert "scatter-chart" in pages["architecture.html"]

    def test_plugins_page_lists_plugins(self):
        pages = site.build_pages(_result())
        assert "pluginpill" in pages["plugins.html"]

    def test_processes_page_polls_api(self):
        pages = site.build_pages(_result())
        assert "/api/processes" in pages["processes.html"]

    def test_modules_page_has_metrics_columns(self):
        pages = site.build_pages(_result())
        m = pages["modules.html"]
        assert ">Ca<" in m and ">Zone<" in m

    def test_ai_page_has_copy_buttons(self):
        pages = site.build_pages(_result())
        assert "gsCopy(" in pages["ai.html"]

    def test_prompts_js_asset_and_external_includes(self):
        pages = site.build_pages(_result())
        assert "prompts.js" in pages
        assert pages["prompts.js"].startswith("window.GS_PROMPTS")
        # overview and graph reference the shared prompts asset + prompt buttons
        for name in ("index.html", "graph.html", "findings.html"):
            assert 'src="prompts.js"' in pages[name]
            assert "gsCopyPrompt(" in pages[name]
        # Prompt buttons use a data attribute (no inline JS-string interpolation).
        assert "data-prompt-key" in pages["findings.html"]
        assert "onclick=\"gsCopyPrompt" not in pages["findings.html"]

    def test_status_bar_on_every_page(self):
        pages = site.build_pages(_result())
        for name in ("index.html", "graph.html", "plugins.html", "processes.html"):
            assert 'id="statusbar"' in pages[name]
            assert "sb-proc" in pages[name]

    def test_graph_overlay_modes_and_highlight(self):
        g = site.build_pages(_result())["graph.html"]
        assert "gv-overlay" in g
        assert "gv-mode" in g and "Abstraction layers" in g
        assert "gv-highlight" in g and "cycles" in g
        assert "Ctrl" in g  # zoom hint

    def test_modules_page_version_columns(self):
        m = site.build_pages(_result())["modules.html"]
        assert ">JVM<" in m and ">Compat<" in m and ">Languages<" in m

    def test_plugins_drilldown(self):
        p = site.build_pages(_result())["plugins.html"]
        assert "plugin-modules" in p and "modlist" in p

    def test_architecture_glossary_and_charts(self):
        a = site.build_pages(_result())["architecture.html"]
        assert "glossary" in a
        assert "Instability" in a and "Distance from the main sequence" in a
        assert a.count("hbar-chart") >= 3  # per-metric charts

    def test_processes_system_header(self):
        p = site.build_pages(_result())["processes.html"]
        assert "pr-sys" in p and "/api/system" in p
        assert "Open log" in p

    def test_languages_widget_shows_versions(self):
        from gradlescope.model import Module, Plugin, Repo

        a = Module(path=":a", directory="/r/a", plugins=[Plugin(id="java")],
                   languages={"java"}, jvm_toolchain="21")
        b = Module(path=":b", directory="/r/b", plugins=[Plugin(id="java")],
                   languages={"java"}, jvm_toolchain="17")
        result = build_result(Repo(root="/r", modules=[a, b], gradle_version="8.6"), generated_at="t")
        idx = site.build_pages(result)["index.html"]
        assert "java 21" in idx and "java 17" in idx

    def test_findings_script_neutralizes_breakout_payload(self):
        from gradlescope.model import Finding, Severity

        result = _result()
        result.findings.append(
            Finding(
                rule_id="x",
                title="t",
                severity=Severity.LOW,
                category="dependency-hygiene",
                message="evil </script><script>alert(1)</script>",
            )
        )
        pages = site.build_pages(result)
        # Findings page loads prompts via an external asset (no inline breakout risk)…
        assert "prompts.js" in pages["findings.html"]
        # …and the prompts asset itself escapes '<' as defense in depth.
        js = pages["prompts.js"]
        assert "</script><script>alert(1)" not in js
        assert "\\u003c/script>" in js

    def test_trend_with_history(self):
        history = [{"generated_at": "2025-12-01T00:00", "overall": 40.0}]
        pages = site.build_pages(_result(), history=history)
        assert "line-chart" in pages["index.html"]

    def test_render_site_writes_files(self, tmp_path):
        out = site.render_site(_result(), str(tmp_path / "site"))
        assert os.path.isfile(os.path.join(out, "index.html"))
        assert os.path.isfile(os.path.join(out, "data.json"))
        assert os.path.isfile(os.path.join(out, "report.md"))
        assert os.path.isfile(os.path.join(out, "ai.md"))

    def test_render_site_live_injects_controls(self, tmp_path):
        out = site.render_site(_result(), str(tmp_path / "live"), live=True)
        with open(os.path.join(out, "index.html"), encoding="utf-8") as fh:
            assert "gsRescan()" in fh.read()
