from __future__ import annotations

import asyncio
import hashlib
import re
import time
import unicodedata
import zlib
from pathlib import Path
from urllib.parse import urljoin, urlparse

class AsyncRateLimiter:
    def __init__(self, rps: float):
        self.interval = 0 if rps <= 0 else 1.0 / rps
        self.lock = asyncio.Lock()
        self.next_time = 0.0

    async def acquire(self) -> None:
        if self.interval <= 0:
            return
        async with self.lock:
            now = time.monotonic()
            delay = self.next_time - now
            if delay > 0:
                await asyncio.sleep(delay)
            now = time.monotonic()
            self.next_time = max(now, self.next_time) + self.interval


def norm_text(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


def norm_name(s: str | None) -> str:
    x = norm_text(s).upper()
    x = re.sub(r"\b(INCORPORATED|INCORPORATION|INC|CORPORATION|CORP|LIMITED|LTD|PLC|LP|L P|ULC|CO|COMPANY)\b", " ", x)
    x = re.sub(r"[^A-Z0-9]+", " ", x)
    return re.sub(r"\s+", " ", x).strip()


WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}

def safe_token(s: str | None, max_len: int = 80) -> str:
    s = norm_text(s)
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", "_", s).strip(" ._")
    tok = (s or "UNKNOWN")[:max_len]
    if tok.upper() in WIN_RESERVED:
        tok = f"{tok}_"
    return tok


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_pdf(path: Path, min_bytes: int = 5) -> bool:
    if not path.exists() or path.stat().st_size < min_bytes:
        return False
    with path.open("rb") as fh:
        return fh.read(5) == b"%PDF-"


def in_shard(key: str, count: int, index: int) -> bool:
    if count <= 1:
        return True
    return (zlib.crc32(key.encode("utf-8")) & 0xFFFFFFFF) % count == index


def absolute_url(base: str, href: str) -> str:
    return urljoin(base, href)


def same_site(a: str, b: str) -> bool:
    ha = urlparse(a).hostname or ""
    hb = urlparse(b).hostname or ""
    return ha.lower().removeprefix("www.") == hb.lower().removeprefix("www.")
