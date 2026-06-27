"""Tests for the dashboard server's routing and actions (no real sockets)."""
import json
import os

from gradlescope.server.app import DashboardServer, is_valid_task
from gradlescope.server.jobs import JobManager, default_stream_runner, gradle_processes


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _make_repo(root):
    _write(os.path.join(root, "settings.gradle"), "include ':app'\n")
    _write(os.path.join(root, "app", "build.gradle"), "plugins { id 'java' }\n")


def _emit_runner(lines, rc=0):
    def runner(argv, cwd, emit, on_start=None):
        for ln in lines:
            emit(ln)
        return rc

    return runner


def _server(tmp_path, job_runner=None, ps_fn=None, output_dir=None):
    root = str(tmp_path)
    _make_repo(root)
    clock = iter([f"2026-01-{d:02d}T00:00:00" for d in range(1, 28)])
    return DashboardServer(
        root=root, job_runner=job_runner, ps_fn=ps_fn, output_dir=output_dir,
        now_fn=lambda: next(clock),
    )


class TestTaskValidation:
    def test_valid(self):
        assert is_valid_task("build")
        assert is_valid_task(":app:test")
        assert is_valid_task("--dry-run build")

    def test_invalid(self):
        assert not is_valid_task("")
        assert not is_valid_task("build; rm -rf /")
        assert not is_valid_task("$(whoami)")
        assert not is_valid_task("--init-script evil.gradle")


class TestServeStatic:
    def test_get_root_serves_index(self, tmp_path):
        srv = _server(tmp_path)
        status, ctype, body = srv.handle("GET", "/", b"")
        assert status == 200 and "text/html" in ctype and "gradlescope" in body

    def test_pages_are_live(self, tmp_path):
        _, _, body = _server(tmp_path).handle("GET", "/index.html", b"")
        assert "gsRescan()" in body

    def test_get_data_json(self, tmp_path):
        status, ctype, body = _server(tmp_path).handle("GET", "/data.json", b"")
        assert status == 200 and "application/json" in ctype
        assert json.loads(body)["tool"] == "gradlescope"

    def test_unknown_path_404(self, tmp_path):
        status, _, _ = _server(tmp_path).handle("GET", "/nope.html", b"")
        assert status == 404


class TestApi:
    def test_status_includes_running_jobs(self, tmp_path):
        status, _, body = _server(tmp_path).handle("GET", "/api/status", b"")
        data = json.loads(body)
        assert "overall" in data and "running_jobs" in data

    def test_rescan_updates_history(self, tmp_path):
        srv = _server(tmp_path)
        status, _, body = srv.handle("POST", "/api/rescan", b"")
        assert status == 200 and json.loads(body)["ok"] is True
        srv.handle("POST", "/api/rescan", b"")
        assert len(srv.history) >= 2

    def test_run_starts_job_and_streams_output(self, tmp_path):
        srv = _server(tmp_path, job_runner=_emit_runner(["Configuring", "BUILD SUCCESSFUL"], rc=0))
        status, _, body = srv.handle("POST", "/api/run", json.dumps({"task": "build"}).encode())
        assert status == 200
        job_id = json.loads(body)["job_id"]
        srv.jobs.wait(job_id)
        # job list
        _, _, jobs_body = srv.handle("GET", "/api/jobs", b"")
        assert len(json.loads(jobs_body)["jobs"]) == 1
        # job detail with streamed lines
        _, _, detail = srv.handle("GET", f"/api/jobs/{job_id}", b"")
        d = json.loads(detail)
        assert d["status"] == "ok"
        assert "BUILD SUCCESSFUL" in d["lines"]

    def test_run_failure_marks_failed(self, tmp_path):
        srv = _server(tmp_path, job_runner=_emit_runner(["boom"], rc=1))
        _, _, body = srv.handle("POST", "/api/run", json.dumps({"task": "build"}).encode())
        job_id = json.loads(body)["job_id"]
        srv.jobs.wait(job_id)
        d = json.loads(srv.handle("GET", f"/api/jobs/{job_id}", b"")[2])
        assert d["status"] == "failed" and d["returncode"] == 1

    def test_job_detail_offset(self, tmp_path):
        srv = _server(tmp_path, job_runner=_emit_runner(["a", "b", "c"]))
        _, _, body = srv.handle("POST", "/api/run", json.dumps({"task": "build"}).encode())
        job_id = json.loads(body)["job_id"]
        srv.jobs.wait(job_id)
        d = json.loads(srv.handle("GET", f"/api/jobs/{job_id}?offset=2", b"")[2])
        assert d["lines"] == ["c"]
        assert d["next_offset"] == 3

    def test_unknown_job_404(self, tmp_path):
        status, _, _ = _server(tmp_path).handle("GET", "/api/jobs/9999", b"")
        assert status == 404

    def test_offset_non_decimal_does_not_crash(self, tmp_path):
        # A Unicode-digit offset (isdigit() True but int() raises) must be safe.
        srv = _server(tmp_path, job_runner=_emit_runner(["a", "b"]))
        _, _, body = srv.handle("POST", "/api/run", json.dumps({"task": "build"}).encode())
        job_id = json.loads(body)["job_id"]
        srv.jobs.wait(job_id)
        status, _, detail = srv.handle("GET", f"/api/jobs/{job_id}?offset=²", b"")
        assert status == 200
        assert json.loads(detail)["lines"] == ["a", "b"]  # treated as offset 0

    def test_run_rejects_invalid_task(self, tmp_path):
        srv = _server(tmp_path, job_runner=_emit_runner([]))
        status, _, _ = srv.handle("POST", "/api/run", json.dumps({"task": "build; rm -rf /"}).encode())
        assert status == 400

    def test_run_default_task_when_missing(self, tmp_path):
        seen = {}

        def runner(argv, cwd, emit, on_start=None):
            seen["argv"] = argv
            return 0

        srv = _server(tmp_path, job_runner=runner)
        _, _, body = srv.handle("POST", "/api/run", b"{}")
        srv.jobs.wait(json.loads(body)["job_id"])
        assert "help" in seen["argv"]

    def test_system_endpoint(self, tmp_path):
        status, _, body = _server(tmp_path).handle("GET", "/api/system", b"")
        data = json.loads(body)
        assert status == 200 and "cpu_count" in data

    def test_cancel_running_job(self, tmp_path):
        import threading

        started, released = threading.Event(), threading.Event()

        class FakeProc:
            def terminate(self):
                released.set()

        def runner(argv, cwd, emit, on_start=None):
            on_start(FakeProc())
            started.set()
            released.wait(2)
            emit("terminated")
            return -15

        srv = _server(tmp_path, job_runner=runner)
        _, _, body = srv.handle("POST", "/api/run", json.dumps({"task": "build"}).encode())
        job_id = json.loads(body)["job_id"]
        started.wait(2)
        status, _, r = srv.handle("POST", f"/api/jobs/{job_id}/cancel", b"")
        assert status == 200 and json.loads(r)["ok"] is True
        srv.jobs.wait(job_id)
        d = json.loads(srv.handle("GET", f"/api/jobs/{job_id}", b"")[2])
        assert d["status"] == "cancelled"

    def test_open_log_endpoint(self, tmp_path, monkeypatch):
        import gradlescope.server.app as app_mod

        monkeypatch.setattr(app_mod, "reveal_path", lambda p: True)
        out = str(tmp_path / "out")
        srv = _server(tmp_path, job_runner=_emit_runner(["x"]), output_dir=out)
        _, _, body = srv.handle("POST", "/api/run", json.dumps({"task": "build"}).encode())
        job_id = json.loads(body)["job_id"]
        srv.jobs.wait(job_id)
        status, _, r = srv.handle("POST", f"/api/jobs/{job_id}/open", b"")
        assert status == 200 and json.loads(r)["path"].endswith(".log")

    def test_processes_endpoint(self, tmp_path):
        fake_ps = lambda: "12345 01:23 0.5 1.2 java -Dorg.gradle.daemon org.gradle.launcher.daemon.bootstrap.GradleDaemon 8.6\n"
        srv = _server(tmp_path, ps_fn=fake_ps)
        status, _, body = srv.handle("GET", "/api/processes", b"")
        data = json.loads(body)
        assert status == 200
        assert data["processes"] and data["processes"][0]["pid"] == 12345
        assert "jobs" in data


class TestJobManager:
    def test_gradle_executable_prefers_wrapper(self, tmp_path):
        root = str(tmp_path)
        gradlew = os.path.join(root, "gradlew")
        with open(gradlew, "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(gradlew, 0o755)
        jm = JobManager(root)
        assert jm.gradle_executable().endswith("gradlew")

    def test_start_builds_argv(self, tmp_path):
        seen = {}

        def runner(argv, cwd, emit, on_start=None):
            seen["argv"] = argv
            return 0

        jm = JobManager(str(tmp_path), run_fn=runner, now_fn=lambda: "t")
        job = jm.start("build --info")
        jm.wait(job.id)
        assert seen["argv"][-2:] == ["build", "--info"]

    def test_persistence_and_reload(self, tmp_path):
        out = str(tmp_path / "out")
        jm = JobManager(str(tmp_path / "repo"), output_dir=out, run_fn=_emit_runner(["x"]), now_fn=lambda: "t")
        job = jm.start("build")
        jm.wait(job.id)
        assert os.path.isfile(os.path.join(out, "jobs", f"{job.id}.json"))
        # a fresh manager reloads persisted jobs
        jm2 = JobManager(str(tmp_path / "repo"), output_dir=out, now_fn=lambda: "t")
        assert job.id in {j["id"] for j in jm2.list()}


class TestProcessesParsing:
    def test_filters_to_gradle(self):
        out = (
            "1 00:01 0.0 0.1 /sbin/launchd\n"
            "222 10:00 1.0 2.0 java org.gradle.launcher.daemon.bootstrap.GradleDaemon 8.6\n"
        )
        procs = gradle_processes(lambda: out)
        assert len(procs) == 1
        assert procs[0]["kind"] == "daemon"

    def test_ps_failure_returns_empty(self):
        def boom():
            raise OSError("no ps")

        assert gradle_processes(boom) == []


class TestStreamRunner:
    def test_streams_and_returns_zero(self):
        import sys

        lines = []
        rc = default_stream_runner([sys.executable, "-c", "print('hello')"], ".", lines.append)
        assert rc == 0 and any("hello" in ln for ln in lines)

    def test_missing_executable(self):
        lines = []
        rc = default_stream_runner(["/no/such/gradle-xyz", "help"], ".", lines.append)
        assert rc == -1 and any("not found" in ln for ln in lines)
