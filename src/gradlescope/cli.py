"""Command-line interface for gradlescope."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import List, Optional

from gradlescope import __version__
from gradlescope.dashboard.site import render_site
from gradlescope.graph.depgraph import DependencyGraph, affected_modules
from gradlescope.report import ai, json_report, markdown_report
from gradlescope.result import build_result
from gradlescope.scan import scan_repo
from gradlescope.server.app import serve as _serve
from gradlescope.workspace import default_site_dir


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_config(path: Optional[str]) -> dict:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"gradlescope: config file not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"gradlescope: invalid JSON in config file {path}: {exc}")


def _load_result(args):
    repo = scan_repo(args.root)
    config = _load_config(getattr(args, "config", None))
    return repo, build_result(repo, config=config, generated_at=_now())


def cmd_scan(args, out=None) -> int:
    out = out or sys.stdout
    _, result = _load_result(args)
    s = result.scorecard
    print(f"Root: {result.root}", file=out)
    print(f"Modules: {result.summary['module_count']}", file=out)
    print(f"Gradle: {result.summary['gradle_version']}", file=out)
    print(f"Languages: {result.summary['languages']}", file=out)
    print(f"Findings: {s.total_findings}  (overall {s.overall} {s.grade})", file=out)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(json_report.to_json(result))
        print(f"Wrote {args.json}", file=out)
    return 0


def cmd_score(args, out=None) -> int:
    out = out or sys.stdout
    _, result = _load_result(args)
    s = result.scorecard
    print(f"Overall: {s.overall} ({s.grade})", file=out)
    for name, cat in sorted(s.categories.items()):
        print(f"  {name:24s} {cat.score:6.1f} {cat.grade}  ({cat.finding_count} findings)", file=out)
    if args.fail_under is not None and s.overall < args.fail_under:
        print(f"FAIL: overall {s.overall} < {args.fail_under}", file=out)
        return 1
    return 0


def cmd_report(args, out=None) -> int:
    out = out or sys.stdout
    _, result = _load_result(args)
    if args.format == "json":
        text = json_report.to_json(result)
    elif args.format == "ai":
        text = ai.ai_markdown(result)
    else:
        text = markdown_report.to_markdown(result)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote {args.out}", file=out)
    else:
        print(text, file=out)
    return 0


def cmd_dashboard(args, out=None) -> int:
    out = out or sys.stdout
    _, result = _load_result(args)
    out_dir = args.out or default_site_dir(args.root)
    history = []
    history_path = os.path.join(out_dir, "history.json")
    if os.path.isfile(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as fh:
                history = json.load(fh)
        except (OSError, ValueError):  # pragma: no cover - defensive
            history = []
    render_site(result, out_dir, history=history, live=args.live)
    # Record this run in history for trend continuity.
    history.append({"generated_at": result.generated_at, "overall": result.scorecard.overall,
                    "grade": result.scorecard.grade})
    with open(history_path, "w", encoding="utf-8") as fh:
        json.dump(history, fh)
    index = os.path.join(out_dir, "index.html")
    print(f"Dashboard written to {index}", file=out)
    if getattr(args, "open", False):  # pragma: no cover - opens a browser
        import webbrowser

        webbrowser.open(f"file://{os.path.abspath(index)}")
    return 0


def cmd_serve(args, out=None) -> int:
    out = out or sys.stdout
    out_dir = args.out or default_site_dir(args.root)
    print(f"Starting gradlescope server for {os.path.abspath(args.root)}", file=out)
    print(f"Workspace: {out_dir}", file=out)
    _serve(root=args.root, host=args.host, port=args.port, config=_load_config(args.config),
           output_dir=out_dir)
    return 0


def cmd_affected(args, out=None) -> int:
    out = out or sys.stdout
    repo = scan_repo(args.root)
    graph = DependencyGraph.from_repo(repo)
    files: List[str] = list(args.file or [])
    if args.from_stdin:
        files.extend(line.strip() for line in sys.stdin if line.strip())
    modules = affected_modules(repo, graph, files)
    if args.format == "json":
        print(json.dumps(modules), file=out)
    else:
        for m in modules:
            print(m, file=out)
    return 0


def cmd_prompt(args, out=None) -> int:
    out = out or sys.stdout
    _, result = _load_result(args)
    if args.list:
        for f in result.findings:
            print(f"{f.key}\t{f.severity.name}\t{f.title}", file=out)
        return 0
    if not args.rule:
        print("error: --rule is required (or use --list)", file=out)
        return 2
    matches = [
        f
        for f in result.findings
        if f.rule_id == args.rule and (args.module is None or f.module_path == args.module)
    ]
    if not matches:
        print(f"No finding matched rule={args.rule} module={args.module}", file=out)
        return 1
    for i, finding in enumerate(matches):
        if i:
            print("\n" + "=" * 70 + "\n", file=out)
        print(ai.finding_prompt(result, finding), file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gradlescope", description="Analyze and improve Gradle monorepo builds.")
    parser.add_argument("--version", action="version", version=f"gradlescope {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--root", default=".", help="Repository root (default: .)")
        p.add_argument("--config", default=None, help="JSON file overriding rule thresholds")

    p_scan = sub.add_parser("scan", help="Scan and print a summary")
    add_common(p_scan)
    p_scan.add_argument("--json", default=None, help="Write the full JSON report to this path")
    p_scan.set_defaults(func=cmd_scan)

    p_score = sub.add_parser("score", help="Print the scorecard")
    add_common(p_score)
    p_score.add_argument("--fail-under", type=float, default=None, help="Exit non-zero if overall score is below this")
    p_score.set_defaults(func=cmd_score)

    p_report = sub.add_parser("report", help="Generate a report")
    add_common(p_report)
    p_report.add_argument("--format", choices=["md", "json", "ai"], default="md")
    p_report.add_argument("--out", default=None, help="Output file (default: stdout)")
    p_report.set_defaults(func=cmd_report)

    p_dash = sub.add_parser("dashboard", help="Generate the static HTML dashboard")
    add_common(p_dash)
    p_dash.add_argument("--out", default=None, help="Output directory (default: ~/.gradlescope/repos/<repo>/site)")
    p_dash.add_argument("--live", action="store_true", help="Inject live controls (for use behind the server)")
    p_dash.add_argument("--open", action="store_true", help="Open the dashboard in a browser")
    p_dash.set_defaults(func=cmd_dashboard)

    p_serve = sub.add_parser("serve", help="Serve a live dashboard with re-scan / run controls")
    add_common(p_serve)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--out", default=None, help="Workspace dir (default: ~/.gradlescope/repos/<repo>)")
    p_serve.set_defaults(func=cmd_serve)

    p_aff = sub.add_parser("affected", help="Print modules affected by changed files")
    add_common(p_aff)
    p_aff.add_argument("--file", action="append", help="A changed file path (repeatable)")
    p_aff.add_argument("--from-stdin", action="store_true", help="Read changed file paths from stdin")
    p_aff.add_argument("--format", choices=["lines", "json"], default="lines")
    p_aff.set_defaults(func=cmd_affected)

    p_prompt = sub.add_parser("prompt", help="Generate an AI prompt to fix a specific finding")
    add_common(p_prompt)
    p_prompt.add_argument("--rule", default=None, help="Rule id of the finding (see --list)")
    p_prompt.add_argument("--module", default=None, help="Module path for a module-level finding")
    p_prompt.add_argument("--list", action="store_true", help="List all finding keys instead")
    p_prompt.set_defaults(func=cmd_prompt)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
