"""Tests for the dashboard server's routing and actions (no sockets)."""
import json
import os

from gradlescope.server.app import DashboardServer, default_runner, is_valid_task


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _make_repo(root):
    _write(os.path.join(root, "settings.gradle"), "include ':app'\n")
    _write(os.path.join(root, "app", "build.gradle"), "plugins { id 'java' }\n")


def _server(tmp_path, runner=None):
    root = str(tmp_path)
    _make_repo(root)
    clock = iter(["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"])
    return DashboardServer(root=root, runner=runner, now_fn=lambda: next(clock))


class TestTaskValidation:
    def test_valid(self):
        assert is_valid_task("build")
        assert is_valid_task(":app:test")
        assert is_valid_task("--dry-run build")

    def test_invalid(self):
        assert not is_valid_task("")
        assert not is_valid_task("build; rm -rf /")
        assert not is_valid_task("build && echo hi")
        assert not is_valid_task("$(whoami)")


class TestServeStatic:
    def test_get_root_serves_index(self, tmp_path):
        srv = _server(tmp_path)
        status, ctype, body = srv.handle("GET", "/", b"")
        assert status == 200
        assert "text/html" in ctype
        assert "gradlescope" in body

    def test_get_named_page(self, tmp_path):
        srv = _server(tmp_path)
        status, _, body = srv.handle("GET", "/findings.html", b"")
        assert status == 200
        assert "Findings" in body

    def test_pages_are_live(self, tmp_path):
        srv = _server(tmp_path)
        _, _, body = srv.handle("GET", "/index.html", b"")
        assert "gsRescan()" in body  # live controls injected

    def test_get_data_json(self, tmp_path):
        srv = _server(tmp_path)
        status, ctype, body = srv.handle("GET", "/data.json", b"")
        assert status == 200
        assert "application/json" in ctype
        assert json.loads(body)["tool"] == "gradlescope"

    def test_unknown_path_404(self, tmp_path):
        srv = _server(tmp_path)
        status, _, _ = srv.handle("GET", "/nope.html", b"")
        assert status == 404


class TestApi:
    def test_status_endpoint(self, tmp_path):
        srv = _server(tmp_path)
        status, ctype, body = srv.handle("GET", "/api/status", b"")
        assert status == 200
        data = json.loads(body)
        assert "overall" in data and "grade" in data

    def test_rescan_updates_and_builds_history(self, tmp_path):
        srv = _server(tmp_path)
        status, _, body = srv.handle("POST", "/api/rescan", b"")
        assert status == 200
        data = json.loads(body)
        assert data["ok"] is True
        assert "overall" in data
        # second rescan -> trend now has a prior point
        srv.handle("POST", "/api/rescan", b"")
        assert len(srv.history) >= 2

    def test_run_uses_injected_runner(self, tmp_path):
        calls = []

        def runner(argv, cwd):
            calls.append((argv, cwd))
            return {"ok": True, "returncode": 0, "output": "BUILD SUCCESSFUL", "message": "ran"}

        srv = _server(tmp_path, runner=runner)
        body = json.dumps({"task": "build"}).encode()
        status, _, resp = srv.handle("POST", "/api/run", body)
        assert status == 200
        assert calls and calls[0][0][-1] == "build"
        assert json.loads(resp)["ok"] is True

    def test_run_rejects_invalid_task(self, tmp_path):
        srv = _server(tmp_path, runner=lambda argv, cwd: {"ok": True})
        body = json.dumps({"task": "build; rm -rf /"}).encode()
        status, _, resp = srv.handle("POST", "/api/run", body)
        assert status == 400

    def test_run_default_task_when_missing(self, tmp_path):
        seen = {}

        def runner(argv, cwd):
            seen["argv"] = argv
            return {"ok": True, "returncode": 0, "output": "", "message": "ok"}

        srv = _server(tmp_path, runner=runner)
        status, _, _ = srv.handle("POST", "/api/run", b"{}")
        assert status == 200
        assert "help" in seen["argv"]

    def test_post_unknown_404(self, tmp_path):
        srv = _server(tmp_path)
        status, _, _ = srv.handle("POST", "/api/nope", b"")
        assert status == 404


class TestDefaultRunner:
    def test_default_runner_handles_missing_executable(self):
        result = default_runner(["/no/such/gradle-xyz", "help"], cwd=".")
        assert result["ok"] is False
        assert "message" in result

    def test_run_gradle_chooses_gradlew_when_present(self, tmp_path):
        # When a wrapper exists, it should be used as the executable.
        gradlew = os.path.join(str(tmp_path), "gradlew")
        with open(gradlew, "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(gradlew, 0o755)
        seen = {}
        srv = _server(tmp_path, runner=lambda argv, cwd: seen.update(argv=argv) or {"ok": True, "message": "ok"})
        srv.run_gradle("build")
        assert seen["argv"][0].endswith("gradlew")
