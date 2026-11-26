"""
core/queue.py – Keskitetty tehtäväjono, rate limiterit ja viestisuojelu.
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from core.logging import log


# ============================================================
# RATE LIMITERS
# ============================================================

class TokenBucket:
    def __init__(self, rate: float = 20.0, burst: int = 10):
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self._tokens) / self._rate)


class UserLimiter:
    def __init__(self, max_req: int = 5, window: float = 60.0):
        self._max = max_req
        self._window = window
        self._data: dict[int, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: int) -> float:
        async with self._lock:
            now = time.monotonic()
            self._data[user_id] = [t for t in self._data[user_id] if now - t < self._window]
            if len(self._data[user_id]) < self._max:
                self._data[user_id].append(now)
                return 0.0
            return max(0.0, min(self._data[user_id]) + self._window - now)


# ============================================================
# MESSAGE GUARD
# ============================================================

class MessageGuard:
    def __init__(self, interval: float = 1.5):
        self._interval = interval
        self._last: dict[int, float] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, mid: int) -> asyncio.Lock:
        if mid not in self._locks:
            self._locks[mid] = asyncio.Lock()
        return self._locks[mid]

    async def wait(self, message_id: int) -> None:
        async with self._get_lock(message_id):
            now = time.monotonic()
            elapsed = now - self._last.get(message_id, 0.0)
            if elapsed < self._interval:
                await asyncio.sleep(self._interval - elapsed)
            self._last[message_id] = time.monotonic()


# ============================================================
# TASK QUEUE
# ============================================================

@dataclass(order=True)
class _QueueItem:
    priority: int
    seq: int
    message_id: int = field(compare=False)
    coro_factory: Callable[[], Awaitable] = field(compare=False)
    user_id: Optional[int] = field(compare=False)
    result_future: Optional[asyncio.Future] = field(compare=False, default=None)


class TaskQueue:
    def __init__(self, workers: int = 3, rate: float = 20.0, burst: int = 10,
                 msg_interval: float = 1.5):
        self._pq: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._global = TokenBucket(rate, burst)
        self._user = UserLimiter()
        self._guard = MessageGuard(msg_interval)
        self._workers_n = workers
        self._tasks: list[asyncio.Task] = []
        self._seq = 0
        self._running = False
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("TaskQueue on suljettu.")
        if self._running:
            return
        self._running = True
        for i in range(self._workers_n):
            self._tasks.append(asyncio.create_task(self._loop(i)))
        log.info("TaskQueue valmis: %d workeria, rate=%.0f/s, msg_interval=%.1fs",
                 self._workers_n, 20.0, self._guard._interval)

    async def stop(self) -> None:
        self._running = False
        self._closed = True
        while not self._pq.empty():
            item = self._pq.get_nowait()
            if item.result_future is not None:
                item.result_future.cancel()
            self._pq.task_done()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _loop(self, wid: int) -> None:
        while self._running:
            try:
                item = await self._pq.get()
            except asyncio.CancelledError:
                return
            try:
                if item.result_future is None or not item.result_future.cancelled():
                    await self._run(item)
            except asyncio.CancelledError:
                if item.result_future is not None:
                    item.result_future.cancel()
                raise
            except Exception as exc:
                if item.result_future and not item.result_future.done():
                    item.result_future.set_exception(exc)
                log.error("TQ worker %d virhe: %s", wid, exc)
            finally:
                self._pq.task_done()

    async def _run(self, item: _QueueItem) -> None:
        await self._global.acquire()
        if item.user_id is not None:
            d = await self._user.acquire(item.user_id)
            if d > 0:
                await asyncio.sleep(d)
        await self._guard.wait(item.message_id)
        result = await item.coro_factory()
        if item.result_future and not item.result_future.done():
            item.result_future.set_result(result)

    async def submit(
        self,
        message_id: int,
        coro_factory: Callable[[], Awaitable],
        user_id: Optional[int] = None,
        priority: int = 0,
    ):
        """Lisää tehtävä johon ja odota tuloksen. Palauttaa koron return-arvon."""
        await self.start()
        self._seq += 1
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        item = _QueueItem(
            priority=priority,
            seq=self._seq,
            message_id=message_id,
            coro_factory=coro_factory,
            user_id=user_id,
            result_future=fut,
        )
        await self._pq.put(item)
        return await fut

    async def submit_priority(
        self,
        message_id: int,
        coro_factory: Callable[[], Awaitable],
        user_id: Optional[int] = None,
        priority: int = 1,
    ):
        """Korkeamman prioriteetin submit (lopulliset viestit). Sama mekaniikka kuin submit."""
        return await self.submit(
            message_id=message_id,
            coro_factory=coro_factory,
            user_id=user_id,
            priority=priority,
        )
