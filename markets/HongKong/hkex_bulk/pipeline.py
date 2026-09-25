from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path

from .db import Database
from .hkex import BASE, HKEXClient
from .utils import (
    candidate_score, choose_canonical_code, clean_text, infer_fiscal_year, json_dumps,
    parse_datetime, sanitize_filename, sha256_file, split_stock_codes,
)


def normalize_filing(raw: dict, active_codes: set[str]) -> dict:
    codes = split_stock_codes(raw.get("STOCK_CODE"))
    canonical = choose_canonical_code(codes, active_codes)
    published = parse_datetime(raw.get("DATE_TIME"))
    title = clean_text(raw.get("TITLE"))
    fy, source, confidence = infer_fiscal_year(title, published)
    link = clean_text(raw.get("FILE_LINK"))
    url = f"{BASE}{link}" if link.startswith("/") else link
    news_id = clean_text(raw.get("NEWS_ID")) or link
    return {
        "news_id": news_id,
        "canonical_code": canonical,
        "stock_codes": ";".join(codes),
        "stock_name": clean_text(raw.get("STOCK_NAME")).replace("<br/>", ";"),
        "title": title,
        "long_text": clean_text(raw.get("LONG_TEXT")),
        "published_at": published.isoformat(sep=" ") if published else None,
        "file_type": clean_text(raw.get("FILE_TYPE")),
        "file_info": clean_text(raw.get("FILE_INFO")),
        "file_link": link,
        "file_url": url,
        "fiscal_year": fy,
        "year_source": source,
        "year_confidence": confidence,
        "score": candidate_score(raw, fy),
        "current_listed": 1 if canonical else 0,
        "raw_json": json_dumps(raw),
    }


async def refresh_active(db: Database, client: HKEXClient) -> int:
    rows = await client.fetch_active_securities()
    return db.upsert_active(rows, datetime.now().isoformat(timespec="seconds"))


async def discover(db: Database, client: HKEXClient, *, start_year: int, end_year: int,
                   publication_end: date, row_limit: int = 2000) -> dict[str, int]:
    active = db.active_codes()
    if not active:
        raise RuntimeError("Active HKEX list is empty. Run active-universe refresh first.")
    pub_start = date(start_year, 1, 1)
    max_end = date(end_year + 1, 12, 31)
    pub_end = min(publication_end, max_end)
    total_raw = total_current = kept_target = 0

    # Calendar-year shards make retries/checkpoint logs understandable; each shard then
    # adaptively splits if HKEX says the result is truncated.
    for py in range(pub_start.year, pub_end.year + 1):
        s = date(py, 1, 1)
        e = min(date(py, 12, 31), pub_end)
        if e < pub_start:
            continue
        s = max(s, pub_start)
        print(f"[discover] publication window {s} .. {e}")
        rows = await client.annual_search_complete(s, e, row_limit=row_limit)
        total_raw += len(rows)
        for raw in rows:
            item = normalize_filing(raw, active)
            if item["current_listed"]:
                total_current += 1
            fy = item["fiscal_year"]
            if item["current_listed"] and fy is not None and start_year <= fy <= end_year:
                kept_target += 1
            db.upsert_filing(item)
        db.commit()
        print(f"[discover] got {len(rows):,} annual-category rows; database checkpoint committed")

    selected = db.select_primaries(start_year, end_year)
    return {"raw_rows": total_raw, "current_rows": total_current, "target_rows": kept_target, "selected": selected}


def _pdf_target(root: Path, row) -> Path:
    code = row["canonical_code"] or "UNKNOWN"
    name = sanitize_filename(row["stock_name"].split(";")[0] if row["stock_name"] else "UNKNOWN")
    year = row["fiscal_year"] or "UNKNOWN"
    news = sanitize_filename(row["news_id"], 40)
    return root / "pdf" / f"{code}_{name}" / str(year) / f"annual_report_{year}_{news}.pdf"


def _valid_pdf(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "file missing"
    if path.stat().st_size < 1024:
        return False, "file is smaller than 1 KB"
    with path.open("rb") as f:
        magic = f.read(5)
    if magic != b"%PDF-":
        return False, f"magic is {magic!r}, expected %PDF-"
    return True, "ok"


async def download_selected(db: Database, client: HKEXClient, *, output: Path, workers: int = 16,
                            limit_reports: int | None = None,
                            stock_codes: list[str] | None = None) -> dict[str, int]:
    db.reset_in_progress()
    rows = db.selected_pending(limit_reports)
    if stock_codes:
        allowed = {s.strip().zfill(5) for s in stock_codes if s}
        rows = [r for r in rows if r["canonical_code"].zfill(5) in allowed]
    queue: asyncio.Queue = asyncio.Queue()
    for r in rows:
        queue.put_nowait(r)
    stats = {"done": 0, "failed": 0, "skipped": 0}
    lock = asyncio.Lock()

    async def worker(worker_id: int) -> None:
        while True:
            try:
                row = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            news_id = row["news_id"]
            target = _pdf_target(output, row)
            part = target.with_suffix(target.suffix + ".part")
            try:
                if target.exists():
                    ok, why = _valid_pdf(target)
                    if ok:
                        digest = sha256_file(target)
                        db.set_download(news_id, "DONE", local_path=str(target), bytes_=target.stat().st_size, sha256=digest)
                        async with lock:
                            stats["skipped"] += 1
                        continue
                    target.unlink(missing_ok=True)

                file_url = row["file_url"] or ""
                file_info = (row["file_info"] or "").lower()
                file_type = (row["file_type"] or "").lower()
                if not file_url:
                    raise RuntimeError("No FILE_LINK/URL in HKEX metadata")
                if "multi" in file_info or "multi" in file_type:
                    raise RuntimeError("HKEX multi-file annual report wrapper: logged for manual/special handling")

                db.set_download(news_id, "DOWNLOADING", local_path=str(target), increment_attempt=True)
                size, content_type, status = await client.stream_pdf(file_url, part)
                ok, why = _valid_pdf(part)
                if not ok:
                    raise RuntimeError(f"Downloaded payload failed PDF validation: {why}; content-type={content_type}")
                target.parent.mkdir(parents=True, exist_ok=True)
                part.replace(target)
                digest = sha256_file(target)
                db.set_download(news_id, "DONE", local_path=str(target), bytes_=size, sha256=digest, http_status=status, error=None)
                async with lock:
                    stats["done"] += 1
                    completed = stats["done"] + stats["failed"] + stats["skipped"]
                    if completed % 25 == 0:
                        print(f"[download] processed {completed:,}/{len(rows):,} this run")
            except Exception as e:
                db.set_download(news_id, "FAILED", local_path=str(target), error=str(e)[:2000])
                async with lock:
                    stats["failed"] += 1
                print(f"[download:FAILED] {row['canonical_code']} FY{row['fiscal_year']} {e}")
            finally:
                queue.task_done()

    tasks = [asyncio.create_task(worker(i)) for i in range(max(1, workers))]
    await asyncio.gather(*tasks)
    return stats
