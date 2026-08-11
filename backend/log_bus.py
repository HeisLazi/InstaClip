"""
Captures every Python logging record into both a ring buffer and a set of
async subscribers (the WS `/stream/logs` endpoint).

The Tkinter app uses a queue; for FastAPI we need:
  - thread-safe ingest (logging may be called from any worker thread)
  - async fan-out to WebSocket clients
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class LogLine:
    ts: float
    level: str
    logger: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


class LogBus:
    """Single-instance log fan-out used by the FastAPI app."""

    def __init__(self, ring_size: int = 5000):
        self._ring: deque[LogLine] = deque(maxlen=ring_size)
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once from the main FastAPI startup event."""
        self._loop = loop

    # ---- producer side ----------------------------------------------------

    def push(self, line: LogLine) -> None:
        with self._lock:
            self._ring.append(line)
            subs = tuple(self._subscribers)
        if self._loop is None or not subs:
            return
        for q in subs:
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, line)
            except RuntimeError:
                # Event loop closed — drop silently.
                pass

    # ---- consumer side ----------------------------------------------------

    def recent(self, n: int = 200) -> list[LogLine]:
        with self._lock:
            return list(self._ring)[-n:]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)


bus = LogBus()


class _BusHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            bus.push(LogLine(
                ts=time.time(),
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
            ))
        except Exception:
            pass


def install(level: int = logging.INFO) -> None:
    """Wire the bus into Python's root logger."""
    handler = _BusHandler()
    handler.setLevel(level)
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == 0 or root.level > level:
        root.setLevel(level)
