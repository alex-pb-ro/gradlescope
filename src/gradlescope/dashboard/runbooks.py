"""A tiny, dependency-free Markdown renderer plus a runbook loader.

We only support the subset of Markdown used by the bundled runbooks: headings,
fenced code blocks, ordered/unordered lists, blockquotes, horizontal rules,
and inline bold/code/links. This keeps the dashboard self-contained.
"""
from __future__ import annotations

import os
import re
from html import escape
from typing import Dict, List, Optional

_CODE_SPAN = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

_RUNBOOKS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "runbooks")


_SAFE_URL_RE = re.compile(r"^(?:https?:|mailto:|#|/|\.{0,2}/|[\w.-]+(?:[/#?]|$))", re.IGNORECASE)


def _is_safe_href(href: str) -> bool:
    """Reject javascript:/data:/vbscript: and other unexpected schemes."""
    return bool(_SAFE_URL_RE.match(href.strip()))


def _render_link(match: "re.Match") -> str:
    label, href = match.group(1), match.group(2)
    if _is_safe_href(href):
        return f'<a href="{href}" rel="noopener">{label}</a>'
    # Unsafe scheme: render as plain (already-escaped) text, no anchor.
    return f"{label} ({href})"


def _inline(text: str) -> str:
    text = escape(text)
    text = _CODE_SPAN.sub(r"<code>\1</code>", text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _LINK.sub(_render_link, text)
    return text


def render_markdown(md: str) -> str:
    lines = md.splitlines()
    out: List[str] = []
    in_code = False
    list_type: Optional[str] = None  # "ul" or "ol"

    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    for raw in lines:
        if raw.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                close_list()
                out.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            out.append(escape(raw))
            continue

        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            close_list()
            continue
        if re.match(r"^#{1,6}\s", stripped):
            close_list()
            level = len(stripped) - len(stripped.lstrip("#"))
            out.append(f"<h{level}>{_inline(stripped[level:].strip())}</h{level}>")
            continue
        if stripped in ("---", "***", "___"):
            close_list()
            out.append("<hr/>")
            continue
        ol = re.match(r"^\d+\.\s+(.*)", stripped)
        ul = re.match(r"^[-*]\s+(.*)", stripped)
        if ol:
            if list_type != "ol":
                close_list()
                out.append("<ol>")
                list_type = "ol"
            out.append(f"<li>{_inline(ol.group(1))}</li>")
            continue
        if ul:
            if list_type != "ul":
                close_list()
                out.append("<ul>")
                list_type = "ul"
            out.append(f"<li>{_inline(ul.group(1))}</li>")
            continue
        if stripped.startswith(">"):
            close_list()
            out.append(f"<blockquote>{_inline(stripped[1:].strip())}</blockquote>")
            continue
        close_list()
        out.append(f"<p>{_inline(stripped)}</p>")

    if in_code:
        out.append("</code></pre>")
    close_list()
    return "\n".join(out)


def _title_of(md: str, fallback: str) -> str:
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


def load_runbooks(directory: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Load runbooks (``*.md``) from a directory into ``{id: {...}}``."""
    directory = directory or _RUNBOOKS_DIR
    runbooks: Dict[str, Dict[str, str]] = {}
    if not os.path.isdir(directory):
        return runbooks
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".md"):
            continue
        rid = name[:-3]
        with open(os.path.join(directory, name), "r", encoding="utf-8") as fh:
            md = fh.read()
        runbooks[rid] = {
            "id": rid,
            "title": _title_of(md, rid),
            "markdown": md,
            "html": render_markdown(md),
        }
    return runbooks
