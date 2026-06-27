"""A small local server for the live dashboard.

The request *routing* (``DashboardServer.handle``) is decoupled from the socket
layer so it can be unit-tested without opening a port. The socket loop
(``serve``) is a thin adapter over the stdlib ``http.server``.

Security notes:
- The server binds to 127.0.0.1 by default.
- Gradle tasks requested from the browser are validated against a strict
  allowlist of characters and executed as an argv list (never via a shell).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from gradlescope.dashboard.site import build_pages
from gradlescope.result import build_result
from gradlescope.scan import scan_repo

_TASK_RE = re.compile(r"^[A-Za-z0-9 :._\-]+$")
Runner = Callable[[List[str], str], Dict]

# Only these CLI flags may be passed from the browser. Notably this excludes
# dangerous options such as --init-script / -I / --include-build / --build-file
# / --project-dir, which can execute arbitrary code or escape the project.
_SAFE_FLAGS = {
    "--dry-run",
    "--parallel",
    "--no-parallel",
    "--build-cache",
    "--no-build-cache",
    "--configuration-cache",
    "--no-configuration-cache",
    "--offline",
    "--continue",
    "--rerun-tasks",
    "--info",
    "--stacktrace",
    "--scan",
    "--no-daemon",
}


def is_valid_task(task: str) -> bool:
    if not task or len(task) >= 200 or not _TASK_RE.match(task):
        return False
    # Every token must be either a task name or an explicitly safe flag.
    for token in task.split():
        if token.startswith("-") and token not in _SAFE_FLAGS:
            return False
    return True


def default_runner(argv: List[str], cwd: str, timeout: int = 1800) -> Dict:
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {"ok": False, "returncode": -1, "output": "", "message": "Gradle executable not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "output": "", "message": "Gradle run timed out"}
    output = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(output.splitlines()[-60:])
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "returncode": proc.returncode,
        "output": tail,
        "message": "BUILD OK" if ok else f"BUILD FAILED (rc={proc.returncode})",
    }


class DashboardServer:
    def __init__(
        self,
        root: str,
        config: Optional[Dict] = None,
        output_dir: Optional[str] = None,
        runner: Optional[Runner] = None,
        now_fn: Optional[Callable[[], str]] = None,
    ):
        self.root = os.path.abspath(root)
        self.config = config or {}
        self.output_dir = output_dir
        self.runner: Runner = runner or default_runner
        self.now_fn = now_fn or (lambda: datetime.now().isoformat(timespec="seconds"))
        # Guards the shared mutable state (result/pages/history) which is read
        # and written from multiple request threads under ThreadingHTTPServer.
        self._lock = threading.RLock()
        self.history: List[Dict] = []
        self.result = None
        self.pages: Dict[str, str] = {}
        self.rescan()

    # -- actions ---------------------------------------------------------- #
    def rescan(self) -> Dict:
        repo = scan_repo(self.root)
        result = build_result(repo, config=self.config, generated_at=self.now_fn())
        with self._lock:
            # Build pages with prior history; the trend chart appends current.
            self.result = result
            self.pages = build_pages(result, history=list(self.history), live=True)
            self.history.append(
                {
                    "generated_at": result.generated_at,
                    "overall": result.scorecard.overall,
                    "grade": result.scorecard.grade,
                }
            )
            self._persist_history()
        return {
            "ok": True,
            "message": f"Re-scanned: {result.scorecard.overall} ({result.scorecard.grade})",
            "overall": result.scorecard.overall,
            "grade": result.scorecard.grade,
        }

    def _persist_history(self) -> None:
        if not self.output_dir:
            return
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            with open(os.path.join(self.output_dir, "history.json"), "w", encoding="utf-8") as fh:
                json.dump(self.history, fh)
        except OSError:  # pragma: no cover - defensive
            pass

    def _gradle_executable(self) -> str:
        wrapper = os.path.join(self.root, "gradlew")
        if os.path.isfile(wrapper) and os.access(wrapper, os.X_OK):
            return wrapper
        return "gradle"

    def run_gradle(self, task: str) -> Dict:
        argv = [self._gradle_executable(), *task.split()]
        return self.runner(argv, self.root)

    def status_summary(self) -> Dict:
        with self._lock:
            s = self.result.scorecard
            return {
                "overall": s.overall,
                "grade": s.grade,
                "total_findings": s.total_findings,
                "severity_counts": s.severity_counts,
                "generated_at": self.result.generated_at,
                "run_count": len(self.history),
            }

    # -- routing ---------------------------------------------------------- #
    def handle(self, method: str, path: str, body: bytes) -> Tuple[int, str, str]:
        path = path.split("?", 1)[0]
        if method == "GET":
            return self._handle_get(path)
        if method == "POST":
            return self._handle_post(path, body)
        return self._not_found()

    def _handle_get(self, path: str) -> Tuple[int, str, str]:
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        with self._lock:
            if name in self.pages:
                return 200, "text/html; charset=utf-8", self.pages[name]
            if name == "data.json":
                return self._json(self.result.to_dict())
        if name == "api/status":
            return self._json(self.status_summary())
        return self._not_found()

    def _handle_post(self, path: str, body: bytes) -> Tuple[int, str, str]:
        if path == "/api/rescan":
            return self._json(self.rescan())
        if path == "/api/run":
            task = self._task_from_body(body)
            if not is_valid_task(task):
                return self._json({"ok": False, "message": "invalid task"}, status=400)
            return self._json(self.run_gradle(task))
        return self._not_found()

    @staticmethod
    def _task_from_body(body: bytes) -> str:
        if not body:
            return "help"
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return ""
        return str(data.get("task", "help")).strip()

    @staticmethod
    def _json(obj: Dict, status: int = 200) -> Tuple[int, str, str]:
        return status, "application/json; charset=utf-8", json.dumps(obj)

    @staticmethod
    def _not_found() -> Tuple[int, str, str]:
        return 404, "text/plain; charset=utf-8", "Not found"


def _make_handler(server: "DashboardServer"):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def _dispatch(self, method: str) -> None:
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                length = 0
            body = self.rfile.read(length) if length else b""
            try:
                status, ctype, payload = server.handle(method, self.path, body)
            except Exception:  # never leak a traceback to the client
                status, ctype, payload = 500, "text/plain; charset=utf-8", "Internal error"
            data = payload.encode("utf-8") if isinstance(payload, str) else payload
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def log_message(self, *_args):
            pass

    return Handler


def build_server(root, host="127.0.0.1", port=8765, config=None, output_dir=None):
    """Build (but do not start) the HTTP server. Returns the httpd; the backing
    :class:`DashboardServer` is attached as ``httpd.gradlescope_server``."""
    from http.server import ThreadingHTTPServer

    server = DashboardServer(root=root, config=config, output_dir=output_dir)
    httpd = ThreadingHTTPServer((host, port), _make_handler(server))
    httpd.gradlescope_server = server
    return httpd


def serve(  # pragma: no cover - blocking socket loop, exercised via build_server in tests
    root: str,
    host: str = "127.0.0.1",
    port: int = 8765,
    config: Optional[Dict] = None,
    output_dir: Optional[str] = None,
) -> None:
    httpd = build_server(root, host, port, config=config, output_dir=output_dir)
    print(f"gradlescope dashboard on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
