from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import deque
from pathlib import Path

class AsyncRateLimiter:
    def __init__(self, rate: float):
        self.rate = max(float(rate), 0.1)
        self._events: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            delay = 0.0
            async with self._lock:
                now = time.monotonic()
                while self._events and now - self._events[0] >= 1.0:
                    self._events.popleft()
                if len(self._events) < max(1, int(self.rate)):
                    self._events.append(now)
                    return
                delay = 1.0 - (now - self._events[0])
            if delay > 0:
                await asyncio.sleep(delay)



def safe_name(value: str, max_len: int = 100) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().rstrip(".")
    value = re.sub(r"\s+", " ", value)
    return value[:max_len] or "UNKNOWN"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False
