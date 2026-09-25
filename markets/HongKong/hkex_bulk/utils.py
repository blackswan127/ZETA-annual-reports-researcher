from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").replace("\r", " ").strip()


def split_stock_codes(raw: object) -> list[str]:
    text = clean_text(raw)
    if not text:
        return []
    text = text.replace("<br />", "<br/>").replace("<br>", "<br/>")
    parts = [p.strip() for p in text.split("<br/>")]
    out: list[str] = []
    for p in parts:
        digits = re.sub(r"\D", "", p)
        if digits:
            out.append(digits.zfill(5)[-5:])
    return list(dict.fromkeys(out))


def choose_canonical_code(codes: Iterable[str], active_codes: set[str]) -> str | None:
    codes = list(codes)
    active = [c for c in codes if c in active_codes]
    if active:
        # HKEX filing rows normally put the issuer's primary counter first.
        # Prefer a conventional <80000 counter if a dual RMB counter is also present.
        preferred = [c for c in active if int(c) < 80000]
        return (preferred or active)[0]
    return None


def infer_fiscal_year(title: str, published_at: datetime | None) -> tuple[int | None, str, str]:
    years = [int(y) for y in YEAR_RE.findall(title or "")]
    if years:
        if published_at:
            plausible = [y for y in years if published_at.year - 2 <= y <= published_at.year + 1]
            if plausible:
                return max(plausible), "title", "high"
        return max(years), "title", "high"
    if published_at:
        # Common HKEX pattern: calendar-year issuers publish Jan-Jun of next year;
        # Mar/Jun year-end issuers often publish Jul-Dec of the same year.
        fy = published_at.year - 1 if published_at.month <= 6 else published_at.year
        return fy, "publication_heuristic", "low"
    return None, "unknown", "none"


def parse_datetime(value: object) -> datetime | None:
    s = clean_text(value)
    for fmt in ("%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def parse_size_bytes(value: object) -> int | None:
    s = clean_text(value).upper().replace(" ", "")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB|B)", s)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2)
    mul = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}[unit]
    return int(n * mul)


def candidate_score(row: dict, fiscal_year: int | None) -> float:
    title = clean_text(row.get("TITLE")).lower()
    long_text = clean_text(row.get("LONG_TEXT")).lower()
    file_type = clean_text(row.get("FILE_TYPE")).upper()
    file_info = clean_text(row.get("FILE_INFO"))
    score = 0.0
    if "annual report" in long_text:
        score += 100
    if "annual report" in title:
        score += 40
    if "年報" in title or "年度報告" in title or "年度报告" in title:
        score += 40
    if fiscal_year and str(fiscal_year) in title:
        score += 25
    if file_type == "PDF" or clean_text(row.get("FILE_LINK")).lower().endswith(".pdf"):
        score += 20
    if "supplement" in title or "notification" in title or "request form" in title:
        score -= 60
    if "summary" in title:
        score -= 20
    if "multi" in file_info.lower():
        score -= 25
    size = parse_size_bytes(file_info)
    if size and size > 0:
        score += min(12.0, math.log10(size + 1))
    return score


def sanitize_filename(value: str, max_len: int = 80) -> str:
    value = INVALID_FILENAME.sub("_", value).strip(" ._")
    value = re.sub(r"\s+", "_", value)
    return (value or "UNKNOWN")[:max_len]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def json_dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def iso_today() -> str:
    return date.today().isoformat()
