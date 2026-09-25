from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

class AsyncRateLimiter:
    def __init__(self, rate: float):
        self.rate = max(float(rate), 0.1)
        self.capacity = max(1, int(self.rate))
        self._events: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._events and now - self._events[0] >= 1.0:
                    self._events.popleft()
                if len(self._events) < self.capacity:
                    self._events.append(now)
                    return
                await asyncio.sleep(max(0.01, 1.0 - (now - self._events[0])))


def safe_name(value: str, max_len: int = 100) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().rstrip(".")
    value = re.sub(r"\s+", " ", value)
    return value[:max_len] or "UNKNOWN"


def normalize_name(value: str) -> str:
    s = value.upper().replace("&", " AND ")
    s = re.sub(r"\b(LIMITED|LTD|PRIVATE|PVT|COMPANY|CO|INDIA)\b", " ", s)
    return re.sub(r"[^A-Z0-9]+", "", s)


def normalize_isin(value: str) -> str:
    v = (value or "").strip().upper()
    return v if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{10}", v) else ""


def shard_match(key: str, count: int, index: int) -> bool:
    if count <= 1:
        return True
    digest = hashlib.sha1(key.encode("utf-8", "ignore")).digest()
    return int.from_bytes(digest[:8], "big") % count == index


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(5) == b"%PDF-"
    except OSError:
        return False


def is_zip(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"PK\x03\x04"
    except OSError:
        return False


def infer_kind(url: str, default: str = "PDF") -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".zip"):
        return "ZIP"
    if path.endswith(".pdf"):
        return "PDF"
    return default.upper()
