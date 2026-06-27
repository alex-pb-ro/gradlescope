"""Background Gradle job management and process inspection.

A long Gradle build (30+ minutes) is run as a background *job* whose streamed
output and status are tracked in memory and persisted to disk, so the live
dashboard can show progress and survive page refreshes (and server restarts).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

# A streaming runner: run argv in cwd, call emit(line) per output line, return
# the process exit code.
StreamRunner = Callable[[List[str], str, Callable[[str], None]], int]


def default_stream_runner(argv: List[str], cwd: str, emit: Callable[[str], None]) -> int:
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
    except FileNotFoundError:
        emit("[gradlescope] Gradle executable not found")
        return -1
    assert proc.stdout is not None
    for line in proc.stdout:
        emit(line.rstrip("\n"))
    proc.wait()
    return proc.returncode


@dataclass
class Job:
    id: str
    task: str
    status: str = "running"  # running | ok | failed
    started_at: str = ""
    ended_at: Optional[str] = None
    returncode: Optional[int] = None
    lines: List[str] = field(default_factory=list)
    thread: Optional[threading.Thread] = None

    def meta(self) -> Dict:
        return {
            "id": self.id,
            "task": self.task,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "returncode": self.returncode,
            "line_count": len(self.lines),
        }


class JobManager:
    def __init__(
        self,
        root: str,
        output_dir: Optional[str] = None,
        run_fn: Optional[StreamRunner] = None,
        now_fn: Optional[Callable[[], str]] = None,
    ):
        self.root = os.path.abspath(root)
        self.output_dir = output_dir
        self.run_fn: StreamRunner = run_fn or default_stream_runner
        self.now_fn = now_fn or (lambda: datetime.now().isoformat(timespec="seconds"))
        self._lock = threading.RLock()
        self._seq = 0
        self.jobs: Dict[str, Job] = {}
        self._load_persisted()

    # -- public API ------------------------------------------------------- #
    def gradle_executable(self) -> str:
        wrapper = os.path.join(self.root, "gradlew")
        if os.path.isfile(wrapper) and os.access(wrapper, os.X_OK):
            return wrapper
        return "gradle"

    def start(self, task: str) -> Job:
        with self._lock:
            self._seq += 1
            jid = f"{self._seq:04d}"
            job = Job(id=jid, task=task, started_at=self.now_fn())
            self.jobs[jid] = job
            self._persist(job)
        argv = [self.gradle_executable(), *task.split()]
        thread = threading.Thread(target=self._run, args=(job, argv), daemon=True)
        job.thread = thread
        thread.start()
        return job

    def list(self) -> List[Dict]:
        with self._lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.started_at, reverse=True)
            return [j.meta() for j in jobs]

    def get(self, job_id: str, offset: int = 0) -> Optional[Dict]:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            offset = max(0, offset)
            return {**job.meta(), "lines": job.lines[offset:], "next_offset": len(job.lines)}

    def wait(self, job_id: str, timeout: float = 10.0) -> None:
        """Block until the job finishes (used by tests)."""
        job = self.jobs.get(job_id)
        if job and job.thread:
            job.thread.join(timeout)

    # -- internals -------------------------------------------------------- #
    def _run(self, job: Job, argv: List[str]) -> None:
        def emit(line: str) -> None:
            with self._lock:
                job.lines.append(line)
                if len(job.lines) % 25 == 0:
                    self._persist(job)

        try:
            rc = self.run_fn(argv, self.root, emit)
        except Exception as exc:  # pragma: no cover - defensive
            emit(f"[gradlescope] runner error: {exc}")
            rc = -1
        with self._lock:
            job.returncode = rc
            job.status = "ok" if rc == 0 else "failed"
            job.ended_at = self.now_fn()
            self._persist(job)

    def _jobs_dir(self) -> Optional[str]:
        if not self.output_dir:
            return None
        return os.path.join(self.output_dir, "jobs")

    def _persist(self, job: Job) -> None:
        d = self._jobs_dir()
        if not d:
            return
        try:
            os.makedirs(d, exist_ok=True)
            payload = {**job.meta(), "lines": job.lines}
            with open(os.path.join(d, f"{job.id}.json"), "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except OSError:  # pragma: no cover - defensive
            pass

    def _load_persisted(self) -> None:
        d = self._jobs_dir()
        if not d or not os.path.isdir(d):
            return
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, name), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):  # pragma: no cover - defensive
                continue
            jid = data.get("id") or name[:-5]
            job = Job(
                id=jid,
                task=data.get("task", ""),
                status=("failed" if data.get("status") == "running" else data.get("status", "ok")),
                started_at=data.get("started_at", ""),
                ended_at=data.get("ended_at"),
                returncode=data.get("returncode"),
                lines=list(data.get("lines", [])),
            )
            self.jobs[jid] = job
            try:
                self._seq = max(self._seq, int(jid))
            except ValueError:  # pragma: no cover - non-numeric id
                pass


# --------------------------------------------------------------------------- #
# Running Gradle processes / daemons
# --------------------------------------------------------------------------- #

_PS_FIELDS = ("pid", "etime", "pcpu", "pmem", "command")


def _default_ps() -> str:  # pragma: no cover - environment dependent
    proc = subprocess.run(
        ["ps", "-eo", ",".join(_PS_FIELDS)], capture_output=True, text=True, timeout=10
    )
    return proc.stdout


def gradle_processes(ps_fn: Optional[Callable[[], str]] = None) -> List[Dict]:
    """Best-effort list of running Gradle-related processes (daemons, wrappers)."""
    runner = ps_fn or _default_ps
    try:
        out = runner()
    except Exception:  # pragma: no cover - ps missing/blocked
        return []
    procs: List[Dict] = []
    for line in out.splitlines():
        low = line.lower()
        if "gradle" not in low:
            continue
        if not ("gradledaemon" in low or "org.gradle" in low or "gradlew" in low or "gradle-launcher" in low):
            continue
        parts = line.split(None, 4)
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        pid, etime, cpu, mem, command = parts
        kind = "daemon" if "gradledaemon" in low or "gradle-launcher" in low else "process"
        procs.append(
            {
                "pid": int(pid),
                "etime": etime,
                "cpu": cpu,
                "mem": mem,
                "kind": kind,
                "command": command[:200],
            }
        )
    return procs
