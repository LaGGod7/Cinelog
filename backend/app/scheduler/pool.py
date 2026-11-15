"""Worker pool with a bounded producer-consumer priority queue (OS engine).

* bounded buffer protected by a mutex + two counting semaphores (slots / items)
* priority scheduling: USER jobs (spoiler scans) run before BATCH jobs (sync, e-mail)
* retry with exponential back-off, then logged as failed
* queue full: USER producers wait briefly, BATCH jobs are postponed and retried later
"""
from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("cinelog.scheduler")

USER, BATCH = 0, 1


class QueueFull(Exception):
    pass


@dataclass(order=True)
class _Item:
    priority: int
    seq: int
    job: "Job" = field(compare=False)


@dataclass
class Job:
    name: str
    fn: Callable[[], Any]
    priority: int = BATCH
    max_retries: int = 3
    attempts: int = 0
    on_done: Optional[Callable[[Any], None]] = None


class BoundedPriorityQueue:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._heap: List[_Item] = []
        self._mutex = threading.Lock()
        self._slots = threading.Semaphore(capacity)
        self._items = threading.Semaphore(0)
        self._seq = itertools.count()

    def put(self, job: Job, timeout: Optional[float] = None) -> None:
        if not self._slots.acquire(timeout=timeout if timeout is not None else None):
            raise QueueFull()
        with self._mutex:
            heapq.heappush(self._heap, _Item(job.priority, next(self._seq), job))
        self._items.release()

    def get(self, timeout: Optional[float] = None) -> Optional[Job]:
        if not self._items.acquire(timeout=timeout):
            return None
        with self._mutex:
            if not self._heap:  # woken by shutdown
                return None
            item = heapq.heappop(self._heap)
        self._slots.release()
        return item.job

    def __len__(self) -> int:
        with self._mutex:
            return len(self._heap)


class WorkerPool:
    def __init__(self, workers: int = 4, capacity: int = 256, backoff_base: float = 0.5) -> None:
        self.queue = BoundedPriorityQueue(capacity)
        self.workers = workers
        self.backoff_base = backoff_base
        self._threads: List[threading.Thread] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._outstanding = 0  # submitted but not finished/failed (includes delayed retries)
        self.stats: Dict[str, int] = {"submitted": 0, "done": 0, "failed": 0, "retried": 0, "postponed": 0}
        self.failed_jobs: List[str] = []

    # ---- lifecycle
    def start(self) -> "WorkerPool":
        if self._threads:
            return self
        self._stop.clear()
        for i in range(self.workers):
            t = threading.Thread(target=self._run, name=f"worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def shutdown(self, wait: bool = True) -> None:
        self._stop.set()
        for _ in self._threads:
            self.queue._items.release()
        if wait:
            for t in self._threads:
                t.join(timeout=2)
        self._threads = []

    # ---- producers
    def submit(self, job: Job, wait: float = 2.0) -> bool:
        with self._lock:
            self._outstanding += 1
            self.stats["submitted"] += 1
        try:
            self.queue.put(job, timeout=wait if job.priority == USER else 0)
            return True
        except QueueFull:
            if job.priority == USER:
                self._finish(failed=True, name=job.name)
                raise
            self.stats["postponed"] += 1
            self._later(job, 1.0)  # postponed: retry when the queue has room
            return False

    def _later(self, job: Job, delay: float) -> None:
        def go() -> None:
            try:
                self.queue.put(job, timeout=0 if job.priority == BATCH else 1.0)
            except QueueFull:
                self._later(job, max(delay, 1.0))

        t = threading.Timer(delay, go)
        t.daemon = True
        t.start()

    # ---- consumers
    def _run(self) -> None:
        while not self._stop.is_set():
            job = self.queue.get(timeout=0.5)
            if job is None:
                continue
            try:
                res = job.fn()
                if job.on_done:
                    job.on_done(res)
                self._finish(name=job.name)
            except Exception as exc:  # noqa: BLE001
                job.attempts += 1
                if job.attempts <= job.max_retries:
                    self.stats["retried"] += 1
                    log.warning("job %s failed (%s); retry %d", job.name, exc, job.attempts)
                    self._later(job, self.backoff_base * (2 ** (job.attempts - 1)))
                else:
                    log.error("job %s failed permanently: %s", job.name, exc)
                    self._finish(failed=True, name=job.name)

    def _finish(self, failed: bool = False, name: str = "") -> None:
        with self._idle:
            self._outstanding -= 1
            self.stats["failed" if failed else "done"] += 1
            if failed:
                self.failed_jobs.append(name)
            if self._outstanding <= 0:
                self._idle.notify_all()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        end = time.time() + timeout
        with self._idle:
            while self._outstanding > 0:
                rem = end - time.time()
                if rem <= 0:
                    return False
                self._idle.wait(rem)
        return True
