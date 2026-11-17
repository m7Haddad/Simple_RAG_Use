"""
Background jobs. Ingest and re-index work runs off the request thread, and each job keeps
a log of progress events that is streamed to the browser over SSE.
"""

import asyncio
import copy
import json
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor

from ..errors import ApiError

log = logging.getLogger(__name__)

TERMINAL_STAGES = {"done", "error"}
MAX_JOBS_KEPT = 50
KEEPALIVE_S = 15


def sse(event: str, data: dict | str) -> str:
    """Format one Server-Sent Event."""
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


class Job:
    """One background job. Its state is a snapshot dict; every emit() appends a copy to the event log."""

    def __init__(self, kind: str, collection_id: str, sources: list[dict]):
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.collection_id = collection_id
        self.started = time.monotonic()
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self.state: dict = {
            "job_id": self.id,
            "kind": kind,
            "collection_id": collection_id,
            "stage": "queued",
            "message": "Waiting to start",
            "elapsed_s": 0.0,
            "stats": {"pages": 0, "characters": 0, "chunks": 0, "embedded": 0, "embedding_pct": 0.0, "indexed": 0},
            "sources": [
                {"source_id": s["source_id"], "name": s["name"], "kind": s["kind"], "status": "pending",
                 "pages": 0, "characters": 0, "chunks": 0, "error": None}
                for s in sources
            ],
            "sample_chunks": [],
            "error": None,
        }

    @property
    def stage(self) -> str:
        return self.state["stage"]

    @property
    def finished(self) -> bool:
        return self.state["stage"] in TERMINAL_STAGES

    def update_source(self, source_id: str, **fields) -> None:
        with self._lock:
            for source in self.state["sources"]:
                if source["source_id"] == source_id:
                    source.update(fields)

    def add_stats(self, **deltas: int) -> None:
        with self._lock:
            for key, value in deltas.items():
                self.state["stats"][key] += value

    def set_stats(self, **values) -> None:
        with self._lock:
            self.state["stats"].update(values)

    def set_samples(self, samples: list[dict]) -> None:
        with self._lock:
            self.state["sample_chunks"] = samples

    def emit(self, stage: str | None = None, message: str | None = None, error: str | None = None) -> None:
        with self._lock:
            if stage:
                self.state["stage"] = stage
            if message is not None:
                self.state["message"] = message
            if error is not None:
                self.state["error"] = error
            self.state["elapsed_s"] = round(time.monotonic() - self.started, 2)
            self.state["seq"] = len(self.events)
            self.events.append(copy.deepcopy(self.state))

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.events[-1] if self.events else self.state)

    def events_from(self, index: int) -> list[dict]:
        with self._lock:
            return self.events[index:]


class JobManager:
    """Runs jobs one at a time on a worker thread, and streams their events."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        # One worker: jobs run one at a time, which keeps memory use predictable
        # and avoids two jobs writing the same index.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")

    def submit(self, kind: str, collection_id: str, sources: list[dict], work: Callable[[Job], None]) -> Job:
        with self._lock:
            if self.active_for(collection_id):
                raise ApiError(409, "job_running", "This collection is already being processed. Wait for it to finish.")
            job = Job(kind, collection_id, sources)
            self._jobs[job.id] = job
            for old_id in list(self._jobs)[:-MAX_JOBS_KEPT]:
                if self._jobs[old_id].finished:
                    del self._jobs[old_id]
        job.emit("queued", "Waiting to start")
        self._executor.submit(self._run, job, work)
        return job

    def _run(self, job: Job, work: Callable[[Job], None]) -> None:
        try:
            work(job)
        except Exception as exc:
            log.exception("Job %s failed", job.id)
            job.emit("error", "Processing failed", error=f"Unexpected error: {exc.__class__.__name__}. See the backend log.")
        if not job.finished:
            job.emit("done", "Finished")

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise ApiError(404, "job_not_found", "Job not found (jobs are kept in memory and reset when the backend restarts)")
        return job

    def active_for(self, collection_id: str) -> Job | None:
        return next((j for j in self._jobs.values() if j.collection_id == collection_id and not j.finished), None)

    async def stream(self, job: Job, is_disconnected: Callable) -> AsyncIterator[str]:
        sent = 0
        last_write = time.monotonic()
        while True:
            if await is_disconnected():
                return
            for event in job.events_from(sent):
                yield sse("progress", event)
                sent += 1
                last_write = time.monotonic()
            if job.finished and sent >= len(job.events):
                return
            if time.monotonic() - last_write > KEEPALIVE_S:
                yield ": keep-alive\n\n"
                last_write = time.monotonic()
            await asyncio.sleep(0.15)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
