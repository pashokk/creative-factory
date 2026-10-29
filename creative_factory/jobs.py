"""Job queue: a JSON file for history plus one worker thread (renders are CPU-heavy, so one at a time)."""

import json
import os
import queue
import shutil
import threading
import time
import traceback
import uuid
from typing import Callable, Optional


class JobStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._jobs: dict[str, dict] = {}
        if os.path.exists(path):
            with open(path) as f:
                self._jobs = json.load(f)
        for job in self._jobs.values():  # a restart killed whatever was running
            if job["status"] in ("queued", "running"):
                job["status"], job["error"] = "failed", "interrupted by a service restart; start it again"
        self._save()

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._jobs, f)
        os.replace(tmp, self.path)

    def create(self, user: str, spec: dict) -> dict:
        job = {"id": uuid.uuid4().hex[:10], "user": user, "spec": spec, "status": "queued", "steps": [],
               "result": None, "error": None, "created": time.time(), "finished": None}
        with self._lock:
            self._jobs[job["id"]] = job
            self._save()
        return job

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            self._jobs[job_id].update(fields)
            self._save()

    def step(self, job_id: str, text: str) -> None:
        with self._lock:
            self._jobs[job_id]["steps"].append({"t": time.time(), "text": text})
            self._save()

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return json.loads(json.dumps(job)) if job else None

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j["created"], reverse=True)[:limit]
            return json.loads(json.dumps(jobs))


class Worker:
    """Runs `handler(spec, work_dir, say) -> result` for each queued job."""

    def __init__(self, store: JobStore, handler: Callable[[dict, str, Callable[[str], None]], dict],
                 work_root: str):
        self.store, self.handler, self.work_root = store, handler, work_root
        self._queue: "queue.Queue[str]" = queue.Queue()
        threading.Thread(target=self._loop, daemon=True, name="render-worker").start()

    def submit(self, user: str, spec: dict) -> dict:
        job = self.store.create(user, spec)
        self._queue.put(job["id"])
        return job

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.store.get(job_id)
            work = os.path.join(self.work_root, job_id)
            self.store.update(job_id, status="running")
            try:
                result = self.handler(job["spec"], work, lambda text: self.store.step(job_id, text))
                self.store.update(job_id, status="done", result=result, finished=time.time())
            except Exception as e:  # shown to the user; details stay in the server log
                traceback.print_exc()
                self.store.update(job_id, status="failed", error=str(e) or type(e).__name__, finished=time.time())
            finally:
                shutil.rmtree(work, ignore_errors=True)
