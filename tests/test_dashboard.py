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
        for name in ["index.html", "findings.html", "modules.html", "graph.html", "runbooks.html", "ai.html"]:
            assert name in pages
            assert pages[name].startswith("<!DOCTYPE html>")

    def test_index_has_gauge_and_charts(self):
        pages = site.build_pages(_result())
        idx = pages["index.html"]
        assert "gauge" in idx
        assert "donut-chart" in idx
        assert "bar-chart" in idx

    def test_findings_page_filterable_rows(self):
        pages = site.build_pages(_result())
        f = pages["findings.html"]
        assert "data-row" in f
        assert "gsFilter()" in f

    def test_ai_page_has_copy_buttons(self):
        pages = site.build_pages(_result())
        assert "gsCopy(" in pages["ai.html"]

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
