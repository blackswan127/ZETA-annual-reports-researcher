"""Concurrent, bounded and resumable PDF transfer engine."""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import fitz
from curl_cffi.requests import AsyncSession

from .catalog import Report, _url


RETRYABLE = {408, 425, 429, 500, 502, 503, 504}
SEC_REQUEST_INTERVAL_S = 1 / 8.8
_PART_NAME = re.compile(r"\.pdf\.[0-9a-f]{32}\.part$")


def native_path(path: Path) -> str:
    """Enable Windows extended paths for deeply nested SOP filenames."""
    value = os.path.abspath(str(path))
    if os.name == "nt" and len(value) >= 240 and not value.startswith("\\\\?\\"):
        return "\\\\?\\" + value
    return value


class RunLock:
    """OS lock: automatically released if the process exits unexpectedly."""

    def __init__(self, state_path: Path):
        self.path = state_path.with_name(state_path.name + ".lock")
        self.stream = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0, os.SEEK_END)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            self.stream = None
            raise ValueError(f"another harvest is using this state database: {self.path}") from exc

    def release(self) -> None:
        if self.stream is None:
            return
        self.stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()
        self.stream = None

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


def cleanup_orphan_parts(root: Path, target_dirs: set[str] | None = None) -> int:
    removed = 0
    if target_dirs is not None:
        for d in target_dirs:
            if os.path.isdir(d):
                for name in os.listdir(d):
                    if _PART_NAME.search(name):
                        try:
                            os.unlink(os.path.join(d, name))
                            removed += 1
                        except OSError:
                            pass
        return removed
    for folder, _, files in os.walk(native_path(root)):
        for name in files:
            if _PART_NAME.search(name):
                os.unlink(os.path.join(folder, name))
                removed += 1
    return removed


class TransferError(Exception):
    def __init__(self, message: str, retryable: bool = True, retry_after_s: float = 0.0):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_s = retry_after_s


def inspect_pdf(payload: bytes) -> int:
    if not payload.startswith(b"%PDF-"):
        raise TransferError("response is not a PDF", retryable=False)
    try:
        with fitz.open(stream=payload, filetype="pdf") as document:
            if document.needs_pass:
                raise TransferError("encrypted PDF requires a password", retryable=False)
            if document.is_repaired or document.page_count < 1:
                raise TransferError("PDF page tree is empty or repaired", retryable=False)
            for page_number in range(document.page_count):
                document.load_page(page_number)
            return document.page_count
    except fitz.FileDataError as exc:
        raise TransferError(f"invalid PDF: {exc}", retryable=False) from exc


def validate_and_store(raw: bytes, report: Report, output_root: Path) -> tuple[int, str]:
    """Keep PDF parsing and durable disk writes off the network event loop."""
    pages = inspect_pdf(raw)
    digest = hashlib.sha256(raw).hexdigest()
    target = output_root / report.relative_path
    staged = target.with_name(f"{target.name}.{uuid.uuid4().hex}.part")
    try:
        os.makedirs(native_path(target.parent), exist_ok=True)
        with open(native_path(staged), "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(native_path(staged), native_path(target))
    except OSError as exc:
        raise TransferError(f"storage error: {exc}", retryable=False) from exc
    finally:
        try:
            os.unlink(native_path(staged))
        except FileNotFoundError:
            pass
    return pages, digest


def interleave_by_host(reports: list[Report]) -> list[Report]:
    groups: dict[str, deque[Report]] = defaultdict(deque)
    for report in reports:
        groups[urlsplit(report.pdf_url).hostname or ""].append(report)
    ordered: list[Report] = []
    while groups:
        for host in list(groups):
            ordered.append(groups[host].popleft())
            if not groups[host]:
                del groups[host]
    return ordered


class RateGate:
    def __init__(self, interval: float):
        self.interval = interval
        self.next_allowed = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_allowed - now)
            self.next_allowed = max(now, self.next_allowed) + self.interval
        if delay:
            await asyncio.sleep(delay)


@dataclass(slots=True)
class Result:
    report: Report
    status: str
    elapsed_s: float = 0.0
    size: int = 0
    pages: int = 0
    sha256: str = ""
    error: str = ""
    retryable: bool = False
    retry_after_s: float = 0.0


class StateStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS reports (
                relative_path TEXT PRIMARY KEY, pdf_url TEXT NOT NULL,
                source_page TEXT NOT NULL, verified INTEGER NOT NULL,
                status TEXT NOT NULL, bytes INTEGER NOT NULL DEFAULT 0,
                pages INTEGER NOT NULL DEFAULT 0, sha256 TEXT NOT NULL DEFAULT '',
                elapsed_s REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )"""
        )
        self.connection.commit()

    def prior(self, report: Report) -> tuple[str, str, int] | None:
        row = self.connection.execute(
            "SELECT status, pdf_url, bytes FROM reports WHERE relative_path=?",
            (str(report.relative_path),),
        ).fetchone()
        return row if row else None

    def schedule(self, reports: list[Report]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.connection.executemany(
            """INSERT INTO reports
            (relative_path, pdf_url, source_page, verified, status, updated_at)
            VALUES (?, ?, ?, ?, 'scheduled', ?)
            ON CONFLICT(relative_path) DO UPDATE SET
            pdf_url=excluded.pdf_url, source_page=excluded.source_page,
            verified=excluded.verified, status='scheduled', error='',
            updated_at=excluded.updated_at""",
            ((str(r.relative_path), r.pdf_url, r.source_page, int(r.verified), now) for r in reports),
        )
        self.connection.commit()

    def save(self, result: Result) -> None:
        self.connection.execute(
            """INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(relative_path) DO UPDATE SET
            pdf_url=excluded.pdf_url, source_page=excluded.source_page,
            verified=excluded.verified, status=excluded.status,
            bytes=excluded.bytes, pages=excluded.pages, sha256=excluded.sha256,
            elapsed_s=excluded.elapsed_s, error=excluded.error,
            updated_at=excluded.updated_at""",
            (
                str(result.report.relative_path), result.report.pdf_url,
                result.report.source_page, int(result.report.verified), result.status,
                result.size, result.pages, result.sha256, result.elapsed_s,
                result.error, datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


@dataclass(frozen=True, slots=True)
class Settings:
    output_root: Path
    state_path: Path
    workers: int = 32
    per_host: int = 2
    timeout_s: float = 15.0
    max_mib: int = 64
    attempts: int = 2
    allow_http: bool = False
    replace: bool = False
    sec_user_agent: str = ""
    companies_house_key: str = ""
    authorized_annualreports: bool = False

    def validate(self) -> None:
        if not 1 <= self.workers <= 128:
            raise ValueError("workers must be 1-128")
        if not 1 <= self.per_host <= self.workers:
            raise ValueError("per_host must be between 1 and workers")
        if self.timeout_s <= 0 or self.max_mib < 1 or not 1 <= self.attempts <= 5:
            raise ValueError("timeout/max_mib/attempts out of range")


def _rate_family(host: str) -> str | None:
    if host == "sec.gov" or host.endswith(".sec.gov"):
        return "sec"
    if host.endswith(".company-information.service.gov.uk"):
        return "companies_house"
    return None


async def _fetch_one(
    report: Report,
    session: AsyncSession,
    settings: Settings,
    host_semaphores: dict[str, asyncio.Semaphore],
    rate_gates: dict[str, RateGate],
    sec_blocked: asyncio.Event,
) -> Result:
    started = time.monotonic()
    try:
        current_url = report.pdf_url
        for redirect in range(6):
            if not _url(current_url, allow_http=settings.allow_http):
                raise TransferError("unsafe redirect target", retryable=False)
            host = urlsplit(current_url).hostname or ""
            if (host == "annualreports.com" or host.endswith(".annualreports.com")) and not settings.authorized_annualreports:
                raise TransferError("AnnualReports.com hosted downloads require --authorized-hosted", retryable=False)
            host_semaphores.setdefault(host, asyncio.Semaphore(settings.per_host))
            async with host_semaphores[host]:
                family = _rate_family(host)
                if family == "sec" and not settings.sec_user_agent:
                    raise TransferError("SEC_USER_AGENT is required for SEC redirects", retryable=False)
                if family == "sec" and sec_blocked.is_set():
                    raise TransferError("SEC 403 circuit open; inspect User-Agent and access rate", retryable=False)
                if family == "companies_house" and not settings.companies_house_key:
                    raise TransferError("COMPANIES_HOUSE_API_KEY is required for Companies House redirects", retryable=False)
                if family:
                    await rate_gates[family].wait()
                if family == "sec" and sec_blocked.is_set():
                    raise TransferError("SEC 403 circuit open; inspect User-Agent and access rate", retryable=False)
                default_ua = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                headers = {
                    "Accept": "application/pdf,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
                    "Accept-Encoding": "identity",
                    "User-Agent": settings.sec_user_agent if family == "sec" else default_ua,
                }
                auth = (settings.companies_house_key, "") if family == "companies_house" else None
                async with session.stream(
                    "GET", current_url, headers=headers, auth=auth,
                    timeout=max(settings.timeout_s, 30.0), allow_redirects=False,
                    impersonate="chrome",
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise TransferError("redirect without Location", retryable=False)
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code != 200:
                        if family == "sec" and response.status_code == 403:
                            sec_blocked.set()
                        retry_after = response.headers.get("retry-after", "")
                        try:
                            retry_after_s = min(300.0, max(0.0, float(retry_after)))
                        except ValueError:
                            try:
                                retry_after_s = min(300.0, max(0.0, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()))
                            except (TypeError, ValueError):
                                retry_after_s = 0.0
                        raise TransferError(
                            f"HTTP {response.status_code}",
                            retryable=response.status_code in RETRYABLE,
                            retry_after_s=retry_after_s,
                        )
                    content_length = response.headers.get("content-length")
                    limit = settings.max_mib * 1024 * 1024
                    if content_length and int(content_length) > limit:
                        raise TransferError("PDF exceeds max_mib", retryable=False)
                    payload = bytearray()
                    async for chunk in response.aiter_content():
                        payload.extend(chunk)
                        if len(payload) > limit:
                            raise TransferError("PDF exceeds max_mib", retryable=False)
                    if content_length and response.headers.get("content-encoding", "identity") == "identity" and len(payload) != int(content_length):
                        raise TransferError("incomplete HTTP body")
                    break
        else:
            raise TransferError("too many redirects", retryable=False)
        raw = bytes(payload)
        pages, digest = await asyncio.to_thread(validate_and_store, raw, report, settings.output_root)
        return Result(report, "downloaded", time.monotonic() - started, len(raw), pages, digest)
    except TransferError as exc:
        return Result(report, "failed", time.monotonic() - started, error=str(exc),
                      retryable=exc.retryable, retry_after_s=exc.retry_after_s)
    except Exception as exc:
        return Result(report, "failed", time.monotonic() - started, error=f"{type(exc).__name__}: {exc}", retryable=True)


async def run(
    reports: list[Report], settings: Settings,
    progress: Callable[[int, int, int, int], None] | None = None,
) -> dict:
    settings.validate()
    if not reports:
        raise ValueError("manifest has no reports")
    if any(not report.verified for report in reports):
        raise ValueError("all report links must be verified=true before downloading")
    hosts = {urlsplit(report.pdf_url).hostname or "" for report in reports}
    if (any(host == "annualreports.com" or host.endswith(".annualreports.com") for host in hosts)
            and not settings.authorized_annualreports):
        raise ValueError("AnnualReports.com hosted downloads require --authorized-hosted")
    if any(_rate_family(host) == "sec" for host in hosts) and not settings.sec_user_agent:
        raise ValueError("SEC_USER_AGENT must identify your organization and contact email")
    if any(_rate_family(host) == "companies_house" for host in hosts) and not settings.companies_house_key:
        raise ValueError("COMPANIES_HOUSE_API_KEY is required for Companies House URLs")

    settings.output_root.mkdir(parents=True, exist_ok=True)
    lock = RunLock(settings.state_path)
    lock.acquire()
    try:
        target_dirs = {native_path(settings.output_root)} | {native_path((settings.output_root / r.relative_path).parent) for r in reports}
        orphan_parts_removed = cleanup_orphan_parts(settings.output_root, target_dirs)
        state = StateStore(settings.state_path)
    except Exception:
        lock.release()
        raise
    started = time.monotonic()
    skipped: list[Result] = []
    recovered: list[Result] = []
    pending: list[Report] = []
    all_attempts: list[Result] = []
    processed = 0
    downloaded = 0
    failed = 0
    try:
        for report in reports:
            target = settings.output_root / report.relative_path
            prior = state.prior(report)
            if os.path.exists(native_path(target)) and not settings.replace:
                if prior and prior[0] == "downloaded" and prior[1] == report.pdf_url and prior[2] == os.path.getsize(native_path(target)):
                    skipped.append(Result(report, "skipped"))
                    continue
                if prior and prior[0] == "scheduled" and prior[1] == report.pdf_url:
                    with open(native_path(target), "rb") as stream:
                        raw = stream.read()
                    pages = await asyncio.to_thread(inspect_pdf, raw)
                    result = Result(report, "downloaded", size=len(raw), pages=pages,
                                    sha256=hashlib.sha256(raw).hexdigest())
                    state.save(result)
                    recovered.append(result)
                    continue
                raise ValueError(f"existing target differs from recorded successful download: {target}")
            pending.append(report)
        state.schedule([report for report in pending
                        if not os.path.exists(native_path(settings.output_root / report.relative_path))])
        initial_pending_count = len(pending)

        host_semaphores = {host: asyncio.Semaphore(settings.per_host) for host in hosts}
        rate_gates = {"sec": RateGate(SEC_REQUEST_INTERVAL_S),
                      "companies_house": RateGate(0.55)}
        sec_blocked = asyncio.Event()
        completed: list[Result] = []
        async with AsyncSession(max_clients=settings.workers) as session:
            for attempt in range(settings.attempts):
                if not pending:
                    break
                ordered = interleave_by_host(pending)
                queue: asyncio.Queue[Report] = asyncio.Queue()
                for report in ordered:
                    queue.put_nowait(report)
                pass_results: list[Result] = []

                async def worker() -> None:
                    nonlocal processed, downloaded, failed
                    while True:
                        try:
                            report = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            return
                        result = await _fetch_one(report, session, settings, host_semaphores,
                                                  rate_gates, sec_blocked)
                        pass_results.append(result)
                        all_attempts.append(result)
                        target = settings.output_root / report.relative_path
                        if not (result.status == "failed" and settings.replace and os.path.exists(native_path(target))):
                            state.save(result)
                        processed += 1
                        downloaded += result.status == "downloaded"
                        failed += result.status == "failed"
                        if progress:
                            progress(processed, len(reports), downloaded, failed)
                        queue.task_done()

                await asyncio.gather(*(worker() for _ in range(min(settings.workers, len(ordered)))))
                if attempt + 1 == settings.attempts:
                    completed.extend(pass_results)
                    break
                pending = [result.report for result in pass_results if result.status == "failed" and result.retryable]
                completed.extend(result for result in pass_results if result.report not in pending)
                if pending:
                    await asyncio.sleep(max(0.5 * (2 ** attempt), *(result.retry_after_s for result in pass_results if result.report in pending)))
        all_results = skipped + recovered + completed
        failures = [r for r in all_results if r.status == "failed"]
        latencies = sorted(r.elapsed_s for r in all_attempts if r.status == "downloaded")

        def percentile(value: float) -> float:
            return round(latencies[max(0, math.ceil(len(latencies) * value) - 1)], 3) if latencies else 0.0

        summary = {
            "requested": len(reports), "downloaded": sum(r.status == "downloaded" for r in completed),
            "skipped": len(skipped), "recovered": len(recovered), "failed": len(failures),
            "bytes": sum(r.size for r in completed if r.status == "downloaded"),
            "elapsed_s": round(time.monotonic() - started, 3),
            "orphan_parts_removed": orphan_parts_removed,
            "p50_latency_s": percentile(0.50), "p95_latency_s": percentile(0.95),
            "p99_latency_s": percentile(0.99),
            "http_429_attempts": sum(r.error == "HTTP 429" for r in all_attempts),
            "http_5xx_attempts": sum(r.error.startswith("HTTP 5") for r in all_attempts),
            "retry_attempts": max(0, len(all_attempts) - initial_pending_count),
            "failures": [{"path": str(r.report.relative_path), "url": r.report.pdf_url, "error": r.error} for r in failures],
        }
        summary["pdfs_per_second"] = round(summary["downloaded"] / max(summary["elapsed_s"], 0.001), 2)
        summary["pdfs_per_minute"] = round(summary["pdfs_per_second"] * 60, 2)
        summary["mib_per_second"] = round(summary["bytes"] / (1024 * 1024) / max(summary["elapsed_s"], 0.001), 2)
        return summary
    finally:
        state.close()
        lock.release()


def verify_store(output_root: Path, state_path: Path, company_keys: set[str] | None = None, deep: bool = True) -> dict:
    connection = sqlite3.connect(state_path)
    errors: list[str] = []
    checked = 0
    seen_content: dict[tuple[str, str], str] = {}
    target_leis = {k.split('|')[2] for k in company_keys if len(k.split('|')) >= 3} if company_keys is not None else None
    parts = []
    try:
        for relative, expected_bytes, expected_pages, expected_sha in connection.execute(
            "SELECT relative_path, bytes, pages, sha256 FROM reports WHERE status='downloaded'"
        ):
            if target_leis is not None:
                p_parts = Path(relative).parts
                lei = p_parts[2].split('_')[0] if len(p_parts) >= 3 else ""
                if lei not in target_leis:
                    continue
            path = output_root / relative
            native_p = native_path(path)
            if not os.path.isfile(native_p):
                errors.append(f"missing: {relative}")
                continue
            if not deep:
                actual_bytes = os.path.getsize(native_p)
                if actual_bytes != expected_bytes:
                    errors.append(f"mismatch: {relative}")
                checked += 1
                part_file = native_p + ".part"
                if os.path.isfile(part_file):
                    parts.append(part_file)
                continue
            with open(native_p, "rb") as stream:
                raw = stream.read()
            try:
                pages = inspect_pdf(raw)
            except TransferError as exc:
                errors.append(f"invalid: {relative}: {exc}")
                continue
            actual_sha = hashlib.sha256(raw).hexdigest()
            if len(raw) != expected_bytes or pages != expected_pages or actual_sha != expected_sha:
                errors.append(f"mismatch: {relative}")
            identity = (str(Path(relative).parent), actual_sha)
            if identity in seen_content:
                errors.append(f"duplicate PDF in fiscal year: {seen_content[identity]} and {relative}")
            else:
                seen_content[identity] = relative
            checked += 1
            part_file = native_p + ".part"
            if os.path.isfile(part_file):
                parts.append(part_file)
    finally:
        connection.close()
    if target_leis is None:
        parts = [os.path.join(folder, name)
                 for folder, _, files in os.walk(native_path(output_root))
                 for name in files if name.endswith(".part")]
    errors.extend(f"orphaned part: {p}" for p in parts)
    return {"checked": checked, "errors": errors, "ok": not errors}
