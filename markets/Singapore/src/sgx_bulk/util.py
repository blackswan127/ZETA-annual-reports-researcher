from __future__ import annotations

import re
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import unquote


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(ch for ch in value if ch.isalnum())


def epoch_ms_datetime(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def epoch_ms_date(value: object) -> date | None:
    dt = epoch_ms_datetime(value)
    return dt.date() if dt else None


def safe_component(value: str, max_len: int = 80) -> str:
    value = unquote(value or "")
    value = re.sub(r"[<>:\\|?*\x00-\x1f\"]", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = "unknown"
    return value[:max_len].rstrip(" .")


def is_pdf_header(data: bytes) -> bool:
    return data.startswith(b"%PDF-")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
