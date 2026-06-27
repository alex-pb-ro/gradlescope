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
