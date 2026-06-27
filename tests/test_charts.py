"""Tests for the self-contained SVG chart builders."""
from gradlescope.dashboard import charts


class TestBarChart:
    def test_renders_one_rect_per_bar(self):
        svg = charts.bar_chart([("a", 3), ("b", 5), ("c", 1)])
        assert svg.startswith("<svg")
        assert svg.count('class="bar"') == 3

    def test_empty_data(self):
        svg = charts.bar_chart([])
        assert "<svg" in svg
        assert svg.count('class="bar"') == 0

    def test_handles_zero_max(self):
        svg = charts.bar_chart([("a", 0), ("b", 0)])
        assert svg.count('class="bar"') == 2


class TestDonut:
    def test_one_segment_per_nonzero_slice(self):
        svg = charts.donut_chart([("hi", 2, "#f00"), ("lo", 3, "#0f0"), ("zero", 0, "#00f")])
        assert svg.count('class="slice"') == 2  # zero slice omitted

    def test_all_zero_renders_placeholder(self):
        svg = charts.donut_chart([("a", 0, "#000")])
        assert "<svg" in svg
        assert svg.count('class="slice"') == 0


class TestGauge:
    def test_shows_value(self):
        svg = charts.gauge(87.5)
        assert "<svg" in svg
        assert "87" in svg

    def test_clamps_range(self):
        assert "<svg" in charts.gauge(150)
        assert "<svg" in charts.gauge(-10)


class TestHBarChart:
    def test_one_row_per_item(self):
        svg = charts.hbar_chart([("a", 3), ("b", 5)])
        assert svg.startswith("<svg")
        assert svg.count('class="hbar"') == 2

    def test_empty(self):
        svg = charts.hbar_chart([])
        assert "<svg" in svg
        assert svg.count('class="hbar"') == 0

    def test_long_label_truncated_with_full_title(self):
        long = ":services:billing:reporting:exporter:csv"
        svg = charts.hbar_chart([(long, 10)])
        assert "…" in svg  # display label truncated
        assert long in svg  # full label preserved in <title>

    def test_per_bar_colors(self):
        svg = charts.hbar_chart([("a", 1), ("b", 2)], colors=["#111111", "#222222"])
        assert "#111111" in svg and "#222222" in svg


class TestScatter:
    def test_points_rendered(self):
        pts = [("m1", 0.2, 0.8, "#f00"), ("m2", 0.9, 0.1, "#0f0")]
        svg = charts.scatter_chart(pts, diagonal=True, x_label="Instability", y_label="Abstractness")
        assert svg.count('class="dot"') == 2
        assert 'class="mainseq"' in svg
        assert "Instability" in svg

    def test_empty_scatter(self):
        svg = charts.scatter_chart([])
        assert "<svg" in svg
        assert svg.count('class="dot"') == 0


class TestLineChart:
    def test_polyline_and_points(self):
        svg = charts.line_chart([("d1", 50), ("d2", 60), ("d3", 80)])
        assert "<polyline" in svg
        assert svg.count('class="pt"') == 3

    def test_single_point(self):
        svg = charts.line_chart([("d1", 50)])
        assert svg.count('class="pt"') == 1

    def test_empty(self):
        assert "<svg" in charts.line_chart([])
