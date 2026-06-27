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
# the process exit code. ``on_start`` (optional) receives the live process
# handle so the manager can cancel it.
StreamRunner = Callable[..., int]


def default_stream_runner(argv, cwd, emit, on_start=None) -> int:
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
    except FileNotFoundError:
        emit("[gradlescope] Gradle executable not found")
        return -1
    if on_start is not None:
        on_start(proc)
    assert proc.stdout is not None
    for line in proc.stdout:
        emit(line.rstrip("\n"))
    proc.wait()
    return proc.returncode


@dataclass
class Job:
    id: str
    task: str
    status: str = "running"  # running | ok | failed | cancelled
    started_at: str = ""
    ended_at: Optional[str] = None
    returncode: Optional[int] = None
    lines: List[str] = field(default_factory=list)
    thread: Optional[threading.Thread] = None
    proc: object = None  # live subprocess.Popen, if any
    cancelled: bool = False

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

    def cancel(self, job_id: str) -> bool:
        """Terminate a running job's process. Returns True if a kill was issued."""
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or job.status != "running":
                return False
            job.cancelled = True
            proc = job.proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:  # pragma: no cover - process already gone
                return False
            return True
        return False

    def log_path(self, job_id: str) -> Optional[str]:
        d = self._jobs_dir()
        if not d or job_id not in self.jobs:
            return None
        return os.path.join(d, f"{job_id}.log")

    # -- internals -------------------------------------------------------- #
    def _run(self, job: Job, argv: List[str]) -> None:
        def emit(line: str) -> None:
            with self._lock:
                job.lines.append(line)
                if len(job.lines) % 25 == 0:
                    self._persist(job)

        def on_start(proc) -> None:
            with self._lock:
                job.proc = proc

        try:
            rc = self.run_fn(argv, self.root, emit, on_start)
        except Exception as exc:  # pragma: no cover - defensive
            emit(f"[gradlescope] runner error: {exc}")
            rc = -1
        with self._lock:
            job.returncode = rc
            job.status = "cancelled" if job.cancelled else ("ok" if rc == 0 else "failed")
            job.ended_at = self.now_fn()
            job.proc = None
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
            # Also write a plain-text log so it can be opened with native tools.
            with open(os.path.join(d, f"{job.id}.log"), "w", encoding="utf-8") as fh:
                fh.write("\n".join(job.lines) + "\n")
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


def reveal_path(path: str) -> bool:  # pragma: no cover - platform dependent
    """Open/reveal a file with the OS file manager (macOS `open -R`, else xdg-open)."""
    import sys

    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path], timeout=10)
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", os.path.dirname(path) or "."], timeout=10)
        else:
            return False
        return True
    except Exception:
        return False


def _read_mem_pct() -> Optional[float]:
    """Best-effort used-memory percentage (Linux /proc, macOS vm_stat)."""
    import sys

    try:
        if sys.platform.startswith("linux") and os.path.exists("/proc/meminfo"):
            info = {}
            with open("/proc/meminfo") as fh:
                for line in fh:
                    k, _, v = line.partition(":")
                    info[k.strip()] = v.strip()
            total = int(info["MemTotal"].split()[0])
            avail = int(info.get("MemAvailable", info.get("MemFree", "0")).split()[0])
            return round((1 - avail / total) * 100, 1) if total else None
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            pages = {}
            for line in out.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    pages[k.strip()] = v.strip().rstrip(".")
            free = int(pages.get("Pages free", "0"))
            spec = int(pages.get("Pages speculative", "0"))
            active = int(pages.get("Pages active", "0"))
            inactive = int(pages.get("Pages inactive", "0"))
            wired = int(pages.get("Pages wired down", "0"))
            used = active + wired
            total = used + inactive + free + spec
            return round(used / total * 100, 1) if total else None
    except Exception:
        return None
    return None


def system_stats() -> Dict:
    """Best-effort system performance snapshot (CPU count, load, memory)."""
    stats: Dict = {"cpu_count": os.cpu_count()}
    try:
        load = os.getloadavg()
        stats["load_avg"] = [round(x, 2) for x in load]
        if stats["cpu_count"]:
            stats["load_pct"] = round(load[0] / stats["cpu_count"] * 100, 1)
    except (OSError, AttributeError):  # pragma: no cover - unavailable on some OSes
        stats["load_avg"] = None
    stats["mem_pct"] = _read_mem_pct()
    return stats


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
