"""Dependency-free SVG chart builders.

Every function returns a self-contained ``<svg>`` string with stable element
classes so output is deterministic and unit-testable. Colors are passed in so
the page theme stays in one place.
"""
from __future__ import annotations

import math
from html import escape
from typing import List, Sequence, Tuple

ACCENT = "#4f7cff"


def _fmt(n: float) -> str:
    return f"{round(n, 2):g}"


def _truncate_tail(label: str, limit: int = 26) -> str:
    """Truncate keeping the most distinguishing tail (good for ``:a:b:c`` paths)."""
    label = str(label)
    if len(label) <= limit:
        return label
    return "…" + label[-(limit - 1):]


def hbar_chart(
    data: Sequence[Tuple[str, float]],
    width: int = 600,
    row_height: int = 24,
    max_value: float = None,
    color: str = ACCENT,
    label_width: int = 180,
    value_suffix: str = "",
    colors: Sequence[str] = None,
) -> str:
    """Horizontal bar chart: one row per item, labels left-aligned and never
    overlapping. Long labels are tail-truncated with a full-text tooltip."""
    n = len(data)
    pad_t, pad_b = 8, 8
    height = pad_t + pad_b + max(n, 1) * row_height
    bar_area = width - label_width - 56
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart hbar-chart" role="img" preserveAspectRatio="xMinYMin meet">']
    if data:
        mv = max_value if max_value is not None else (max((v for _, v in data), default=0) or 1)
        for i, (label, value) in enumerate(data):
            y = pad_t + i * row_height
            bar_h = row_height * 0.62
            bw = max(0.0, (value / mv) * bar_area) if mv else 0.0
            bar_color = colors[i] if colors and i < len(colors) else color
            full = escape(str(label))
            disp = escape(_truncate_tail(label))
            cy = y + row_height / 2
            parts.append(
                f'<text class="hbar-label" x="{label_width - 8}" y="{_fmt(cy)}" text-anchor="end" '
                f'dominant-baseline="central">{disp}<title>{full}</title></text>'
            )
            parts.append(
                f'<rect class="hbar" x="{label_width}" y="{_fmt(y + (row_height - bar_h) / 2)}" '
                f'width="{_fmt(bw)}" height="{_fmt(bar_h)}" rx="3" fill="{bar_color}">'
                f"<title>{full}: {_fmt(value)}{escape(value_suffix)}</title></rect>"
            )
            parts.append(
                f'<text class="hbar-value" x="{_fmt(label_width + bw + 6)}" y="{_fmt(cy)}" '
                f'dominant-baseline="central">{_fmt(value)}{escape(value_suffix)}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def bar_chart(
    data: Sequence[Tuple[str, float]],
    width: int = 480,
    height: int = 220,
    color: str = ACCENT,
    max_value: float = None,
) -> str:
    pad_l, pad_b, pad_t = 40, 28, 12
    plot_w = width - pad_l - 12
    plot_h = height - pad_b - pad_t
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart bar-chart" role="img">']
    parts.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - 12}" y2="{pad_t + plot_h}" class="axis"/>')
    if data:
        max_value = max_value or max((v for _, v in data), default=0) or 1
        n = len(data)
        slot = plot_w / n
        bar_w = max(4, slot * 0.6)
        for i, (label, value) in enumerate(data):
            bar_h = (value / max_value) * plot_h
            x = pad_l + i * slot + (slot - bar_w) / 2
            y = pad_t + plot_h - bar_h
            parts.append(
                f'<rect class="bar" x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(bar_w)}" '
                f'height="{_fmt(bar_h)}" rx="3" fill="{color}"><title>{escape(str(label))}: {_fmt(value)}</title></rect>'
            )
            parts.append(
                f'<text class="bar-label" x="{_fmt(x + bar_w / 2)}" y="{height - 10}" '
                f'text-anchor="middle">{escape(str(label))}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _polar(cx: float, cy: float, r: float, angle_deg: float) -> Tuple[float, float]:
    a = math.radians(angle_deg - 90)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def donut_chart(
    data: Sequence[Tuple[str, float, str]],
    size: int = 200,
    thickness: int = 34,
) -> str:
    cx = cy = size / 2
    r = (size / 2) - 6
    inner = r - thickness
    total = sum(v for _, v, _ in data)
    nonzero = [(label, value, color) for label, value, color in data if value > 0]
    parts = [f'<svg viewBox="0 0 {size} {size}" class="chart donut-chart" role="img">']
    if len(nonzero) == 1:
        # A single 100% slice would be a degenerate arc (start == end) and render
        # nothing — draw a full ring instead.
        label, value, color = nonzero[0]
        parts.append(
            f'<circle class="slice" cx="{cx}" cy="{cy}" r="{_fmt(r - thickness / 2)}" '
            f'fill="none" stroke="{color}" stroke-width="{thickness}">'
            f"<title>{escape(str(label))}: {_fmt(value)}</title></circle>"
        )
    elif total > 0:
        angle = 0.0
        for label, value, color in data:
            if value <= 0:
                continue
            sweep = value / total * 360
            start, end = angle, angle + sweep
            large = 1 if sweep > 180 else 0
            x1, y1 = _polar(cx, cy, r, start)
            x2, y2 = _polar(cx, cy, r, end)
            xi2, yi2 = _polar(cx, cy, inner, end)
            xi1, yi1 = _polar(cx, cy, inner, start)
            d = (
                f"M {_fmt(x1)} {_fmt(y1)} A {_fmt(r)} {_fmt(r)} 0 {large} 1 {_fmt(x2)} {_fmt(y2)} "
                f"L {_fmt(xi2)} {_fmt(yi2)} A {_fmt(inner)} {_fmt(inner)} 0 {large} 0 {_fmt(xi1)} {_fmt(yi1)} Z"
            )
            parts.append(
                f'<path class="slice" d="{d}" fill="{color}"><title>{escape(str(label))}: {_fmt(value)}</title></path>'
            )
            angle = end
    else:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{_fmt(r - thickness/2)}" fill="none" stroke="#e5e7eb" stroke-width="{thickness}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _score_color(value: float) -> str:
    if value >= 90:
        return "#16a34a"
    if value >= 80:
        return "#65a30d"
    if value >= 70:
        return "#d97706"
    if value >= 60:
        return "#ea580c"
    return "#dc2626"


def gauge(value: float, size: int = 180) -> str:
    value = max(0.0, min(100.0, value))
    cx = cy = size / 2
    r = (size / 2) - 14
    color = _score_color(value)
    # Background ring + value arc (full circle proportion).
    circumference = 2 * math.pi * r
    dash = circumference * (value / 100.0)
    parts = [f'<svg viewBox="0 0 {size} {size}" class="chart gauge" role="img">']
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{_fmt(r)}" fill="none" stroke="#eceff4" stroke-width="14"/>')
    parts.append(
        f'<circle cx="{cx}" cy="{cy}" r="{_fmt(r)}" fill="none" stroke="{color}" stroke-width="14" '
        f'stroke-linecap="round" stroke-dasharray="{_fmt(dash)} {_fmt(circumference)}" '
        f'transform="rotate(-90 {cx} {cy})"/>'
    )
    parts.append(
        f'<text class="gauge-value" x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central">{_fmt(value)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def line_chart(
    points: Sequence[Tuple[str, float]],
    width: int = 520,
    height: int = 200,
    color: str = ACCENT,
    y_max: float = 100.0,
) -> str:
    pad_l, pad_b, pad_t, pad_r = 36, 26, 12, 12
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_b - pad_t
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart line-chart" role="img">']
    parts.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" y2="{pad_t + plot_h}" class="axis"/>')
    n = len(points)
    coords: List[Tuple[float, float]] = []
    if n == 1:
        x = pad_l + plot_w / 2
        y = pad_t + plot_h - (points[0][1] / y_max) * plot_h
        coords.append((x, y))
    elif n > 1:
        step = plot_w / (n - 1)
        for i, (_, value) in enumerate(points):
            x = pad_l + i * step
            y = pad_t + plot_h - (min(value, y_max) / y_max) * plot_h
            coords.append((x, y))
    if len(coords) > 1:
        poly = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in coords)
        parts.append(f'<polyline class="line" points="{poly}" fill="none" stroke="{color}" stroke-width="2"/>')
    for (x, y), (label, value) in zip(coords, points):
        parts.append(
            f'<circle class="pt" cx="{_fmt(x)}" cy="{_fmt(y)}" r="3" fill="{color}">'
            f'<title>{escape(str(label))}: {_fmt(value)}</title></circle>'
        )
    parts.append("</svg>")
    return "".join(parts)


def scatter_chart(
    points: Sequence[Tuple[str, float, float, str]],
    width: int = 440,
    height: int = 360,
    x_max: float = 1.0,
    y_max: float = 1.0,
    x_label: str = "x",
    y_label: str = "y",
    diagonal: bool = False,
) -> str:
    """Scatter plot. ``points`` are ``(label, x, y, color)``. With ``diagonal``
    a line from (0, y_max) to (x_max, 0) is drawn (the Clean Architecture
    "main sequence")."""
    pad_l, pad_b, pad_t, pad_r = 40, 34, 14, 14
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_b - pad_t
    x0, y0 = pad_l, pad_t + plot_h

    def px(x):
        return x0 + (min(x, x_max) / x_max if x_max else 0) * plot_w

    def py(y):
        return y0 - (min(y, y_max) / y_max if y_max else 0) * plot_h

    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart scatter-chart" role="img">']
    parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x0 + plot_w}" y2="{y0}" class="axis"/>')
    parts.append(f'<line x1="{x0}" y1="{pad_t}" x2="{x0}" y2="{y0}" class="axis"/>')
    if diagonal:
        parts.append(
            f'<line class="mainseq" x1="{_fmt(px(0))}" y1="{_fmt(py(y_max))}" '
            f'x2="{_fmt(px(x_max))}" y2="{_fmt(py(0))}" stroke="#64748b" stroke-dasharray="4 4"/>'
        )
    for item in points:
        label, x, y, color = item
        parts.append(
            f'<circle class="dot" cx="{_fmt(px(x))}" cy="{_fmt(py(y))}" r="4" fill="{color}" '
            f'fill-opacity="0.8"><title>{escape(str(label))} (x={_fmt(x)}, y={_fmt(y)})</title></circle>'
        )
    parts.append(
        f'<text class="axis-label" x="{_fmt(x0 + plot_w / 2)}" y="{height - 6}" text-anchor="middle">{escape(x_label)}</text>'
    )
    parts.append(
        f'<text class="axis-label" x="12" y="{_fmt(pad_t + plot_h / 2)}" text-anchor="middle" '
        f'transform="rotate(-90 12 {_fmt(pad_t + plot_h / 2)})">{escape(y_label)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)
