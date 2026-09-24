"""Offline-first SEC bulk discovery and FCA NSM CSV ingestion.

The source guides contain research instructions, not a company-level universe.
This module requires a supplied identity roster before it can plan report-years.
"""

from __future__ import annotations

import csv
import asyncio
import hashlib
import io
import json
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from .catalog import Report
from .engine import RateGate, SEC_REQUEST_INTERVAL_S


SEC_BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
FCA_BASE = "https://data.fca.org.uk/"
UNIVERSE_FIELDS = ("country", "company_name", "exchange", "lei", "isin", "ticker", "cik", "aliases")
ANNUAL_FORMS = {"10-K", "20-F", "40-F", "ARS"}
YEAR_PATTERN = re.compile(r"(?<!\d)(20(?:1[7-9]|2[0-5]))(?!\d)")


def parse_years(value: str) -> list[int]:
    match = re.fullmatch(r"(20\d{2}):(20\d{2})", value)
    if not match:
        raise ValueError("years must look like 2017:2025")
    first, last = map(int, match.groups())
    if first > last or first < 1994 or last > 2100:
        raise ValueError("invalid year range")
    return list(range(first, last + 1))


@dataclass(frozen=True, slots=True)
class Company:
    country: str
    company_name: str
    exchange: str
    lei: str
    isin: str
    ticker: str
    cik: str
    aliases: str = ""

    @property
    def key(self) -> str:
        return "|".join((self.country, self.exchange, self.lei, self.isin, self.ticker))

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Company":
        data = {field: (row.get(field) or "").strip() for field in UNIVERSE_FIELDS}
        # Reuse SOP identity validation; the dummy URL is never persisted.
        Report.from_row({**data, "fiscal_year": "FY2024", "report_type": "AR",
                         "language": "EN", "pdf_url": "https://example.org/report.pdf",
                         "source_page": "", "verified": "false"})
        if not data["company_name"]:
            raise ValueError("company_name is required")
        if data["country"] == "USA":
            if not data["cik"].isdigit() or int(data["cik"]) < 1:
                raise ValueError("US companies need a numeric SEC CIK")
            data["cik"] = str(int(data["cik"]))
        elif data["cik"] and not data["cik"].isdigit():
            raise ValueError("CIK must be numeric when supplied")
        return cls(**data)


def read_universe(path: Path) -> list[Company]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or set(reader.fieldnames) != set(UNIVERSE_FIELDS):
            raise ValueError(f"universe columns must be: {', '.join(UNIVERSE_FIELDS)}")
        companies: list[Company] = []
        seen: set[str] = set()
        for line, row in enumerate(reader, start=2):
            try:
                company = Company.from_row(row)
            except ValueError as exc:
                raise ValueError(f"universe line {line}: {exc}") from exc
            if company.key in seen:
                raise ValueError(f"universe line {line}: duplicate listing identity")
            seen.add(company.key)
            companies.append(company)
    if not companies:
        raise ValueError("universe has no companies")
    return companies


class DiscoveryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA temp_store=MEMORY")
        self.connection.executescript(
            """CREATE TABLE IF NOT EXISTS companies (
                company_key TEXT PRIMARY KEY, country TEXT NOT NULL,
                company_name TEXT NOT NULL, exchange TEXT NOT NULL,
                lei TEXT NOT NULL, isin TEXT NOT NULL, ticker TEXT NOT NULL,
                cik TEXT NOT NULL, aliases TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS expected_slots (
                company_key TEXT NOT NULL REFERENCES companies(company_key),
                report_year INTEGER NOT NULL,
                PRIMARY KEY(company_key, report_year)
            );
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY, company_key TEXT NOT NULL,
                report_year INTEGER, source TEXT NOT NULL,
                source_record_id TEXT NOT NULL, source_url TEXT NOT NULL,
                source_format TEXT NOT NULL, form_type TEXT NOT NULL,
                filing_date TEXT NOT NULL, publication_date TEXT NOT NULL,
                report_date TEXT NOT NULL, description TEXT NOT NULL,
                status TEXT NOT NULL, verified INTEGER NOT NULL,
                metadata_json TEXT NOT NULL,
                UNIQUE(source, source_record_id, company_key)
            );
            CREATE INDEX IF NOT EXISTS candidates_company_year
                ON candidates(company_key, report_year);
            CREATE INDEX IF NOT EXISTS candidates_status
                ON candidates(status);
            CREATE TABLE IF NOT EXISTS benchmark_runs (
                id INTEGER PRIMARY KEY, started_at TEXT NOT NULL,
                source TEXT NOT NULL, document_count INTEGER NOT NULL,
                success_count INTEGER NOT NULL, failed_count INTEGER NOT NULL,
                bytes INTEGER NOT NULL, elapsed_s REAL NOT NULL,
                documents_per_second REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fca_historic_url_map (
                old_nsm_url TEXT PRIMARY KEY, fca_url TEXT NOT NULL,
                source_file TEXT NOT NULL, company_name TEXT NOT NULL,
                title TEXT NOT NULL, published_date TEXT NOT NULL
            );"""
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def add_universe(self, companies: list[Company], years: list[int]) -> None:
        self.connection.executemany(
            """INSERT INTO companies VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(company_key) DO UPDATE SET
            company_name=excluded.company_name, cik=excluded.cik,
            aliases=excluded.aliases""",
            ((c.key, c.country, c.company_name, c.exchange, c.lei,
              c.isin, c.ticker, c.cik, c.aliases) for c in companies),
        )
        self.connection.executemany(
            "INSERT OR IGNORE INTO expected_slots VALUES (?,?)",
            ((c.key, year) for c in companies for year in years),
        )
        self.connection.commit()

    def companies(self, country: str | None = None) -> list[Company]:
        if country is not None:
            query = "SELECT * FROM companies WHERE country=?"
            params = (country,)
        else:
            query = "SELECT * FROM companies"
            params = ()
        return [Company(row["country"], row["company_name"], row["exchange"],
                        row["lei"], row["isin"], row["ticker"], row["cik"], row["aliases"])
                for row in self.connection.execute(query, params)]

    def years(self, company_key: str) -> set[int]:
        return {row[0] for row in self.connection.execute(
            "SELECT report_year FROM expected_slots WHERE company_key=?", (company_key,)
        )}

    def upsert_candidate(self, *, company_key: str, report_year: int | None,
                         source: str, source_record_id: str, source_url: str,
                         source_format: str, form_type: str = "",
                         filing_date: str = "", publication_date: str = "",
                         report_date: str = "", description: str = "",
                         status: str = "DISCOVERED", verified: bool = False,
                         metadata: dict | None = None) -> None:
        self.connection.execute(
            """INSERT INTO candidates
            (company_key, report_year, source, source_record_id, source_url,
             source_format, form_type, filing_date, publication_date, report_date,
             description, status, verified, metadata_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source, source_record_id, company_key) DO UPDATE SET
            report_year=excluded.report_year, source_url=excluded.source_url,
            source_format=excluded.source_format, form_type=excluded.form_type,
            filing_date=excluded.filing_date, publication_date=excluded.publication_date,
            report_date=excluded.report_date, description=excluded.description,
            status=excluded.status, verified=excluded.verified,
            metadata_json=excluded.metadata_json""",
            (company_key, report_year, source, source_record_id, source_url,
             source_format, form_type, filing_date, publication_date,
             report_date, description, status, int(verified),
             json.dumps(metadata or {}, separators=(",", ":"))),
        )

    def commit(self) -> None:
        self.connection.commit()

    def status(self) -> dict:
        expected = self.connection.execute("SELECT COUNT(*) FROM expected_slots").fetchone()[0]
        discovered = self.connection.execute(
            """SELECT COUNT(*) FROM expected_slots e WHERE EXISTS (
                SELECT 1 FROM candidates c WHERE c.company_key=e.company_key
                AND c.report_year=e.report_year)"""
        ).fetchone()[0]
        pdf_ready = self.connection.execute(
            "SELECT COUNT(*) FROM candidates WHERE verified=1 AND source_format='pdf' AND report_year IS NOT NULL"
        ).fetchone()[0]
        review = self.connection.execute(
            "SELECT COUNT(*) FROM candidates WHERE status='MANUAL_REVIEW'"
        ).fetchone()[0]
        non_pdf = self.connection.execute(
            "SELECT COUNT(*) FROM candidates WHERE source_format!='pdf'"
        ).fetchone()[0]
        by_source = {row[0]: row[1] for row in self.connection.execute(
            "SELECT source, COUNT(*) FROM candidates GROUP BY source"
        )}
        has_downloads = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reports'"
        ).fetchone() is not None
        if has_downloads:
            download_counts = self.connection.execute(
                """SELECT COUNT(*) FILTER (WHERE status='downloaded'),
                          COUNT(*) FILTER (WHERE status='failed'),
                          COALESCE(SUM(bytes) FILTER (WHERE status='downloaded'),0)
                   FROM reports"""
            ).fetchone()
            verified_slots = self.connection.execute(
                """SELECT COUNT(*) FROM expected_slots e WHERE EXISTS (
                    SELECT 1 FROM candidates c JOIN reports r
                      ON r.pdf_url=c.source_url AND r.status='downloaded'
                    WHERE c.company_key=e.company_key AND c.report_year=e.report_year)"""
            ).fetchone()[0]
        else:
            download_counts = (0, 0, 0)
            verified_slots = 0
        duplicate_years = self.connection.execute(
            """SELECT COUNT(*) FROM (
                SELECT company_key, report_year FROM candidates
                WHERE report_year IS NOT NULL AND status='DISCOVERED'
                GROUP BY company_key, report_year HAVING COUNT(*)>1)"""
        ).fetchone()[0]
        return {"companies": self.connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
                "expected_company_years": expected, "discovered_company_years": discovered,
                "missing_company_years": expected - discovered,
                "pdf_ready_candidates": pdf_ready, "non_pdf_candidates": non_pdf,
                "manual_review_candidates": review,
                "duplicate_company_years": duplicate_years,
                "downloaded_files": download_counts[0], "failed_downloads": download_counts[1],
                "downloaded_bytes": download_counts[2],
                "verified_company_years": verified_slots,
                "completion_pct": round(100 * verified_slots / expected, 2) if expected else 0.0,
                "candidates_by_source": by_source}


def download_sec_bulk(cache_path: Path, user_agent: str, *, max_age_hours: int = 24) -> Path:
    if not user_agent or "@" not in user_agent:
        raise ValueError("SEC_USER_AGENT must contain an organization and contact email")
    if cache_path.exists() and datetime.now().timestamp() - cache_path.stat().st_mtime < max_age_hours * 3600:
        return cache_path
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    staged = cache_path.with_suffix(".zip.part")
    timeout = httpx.Timeout(connect=10, read=90, write=30, pool=30)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}) as client:
            with client.stream("GET", SEC_BULK_URL) as response:
                response.raise_for_status()
                with staged.open("wb") as stream:
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        stream.write(chunk)
        with zipfile.ZipFile(staged) as archive:
            if not archive.namelist():
                raise ValueError("SEC bulk archive is empty")
        staged.replace(cache_path)
    finally:
        staged.unlink(missing_ok=True)
    return cache_path


def sec_archive_url(cik: str, accession: str, primary_document: str) -> str:
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ValueError("invalid SEC accession number")
    if not primary_document or "/" in primary_document or "\\" in primary_document or primary_document in {".", ".."}:
        raise ValueError("invalid SEC primary document")
    return f"{SEC_ARCHIVES}/{int(cik)}/{accession.replace('-', '')}/{primary_document}"


def _sec_rows(data: dict):
    recent = data.get("filings", {}).get("recent", data)
    forms = recent.get("form", [])
    for index, form in enumerate(forms):
        if form not in ANNUAL_FORMS and form not in {f + "/A" for f in ANNUAL_FORMS}:
            continue
        row = {field: values[index] if index < len(values) else ""
               for field, values in recent.items() if isinstance(values, list)}
        yield row


def _ingest_sec_data(store: DiscoveryStore, company: Company, data: dict) -> int:
    target_years = store.years(company.key)
    found = 0
    for row in _sec_rows(data):
        form = row.get("form", "")
        report_date = row.get("reportDate", "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
            continue
        year = int(report_date[:4])
        if year not in target_years:
            continue
        accession = row.get("accessionNumber", "")
        primary = row.get("primaryDocument", "")
        try:
            url = sec_archive_url(company.cik, accession, primary)
        except ValueError:
            continue
        suffix = Path(primary).suffix.lower()
        if form == "ARS" and suffix != ".pdf":
            continue
        source_format = "pdf" if suffix == ".pdf" else "html" if suffix in {".htm", ".html", ".xhtml"} else "txt" if suffix == ".txt" else "unknown"
        is_amendment = form.endswith("/A")
        status = "AMENDMENT" if is_amendment else "DISCOVERED"
        store.upsert_candidate(
            company_key=company.key, report_year=year, source="SEC",
            source_record_id=accession, source_url=url,
            source_format=source_format, form_type=form,
            filing_date=row.get("filingDate", ""), report_date=report_date,
            description=row.get("primaryDocDescription", ""),
            status=status, verified=not is_amendment,
            metadata={"cik": company.cik, "raw": row},
        )
        found += 1
    return found


def discover_sec_bulk(store: DiscoveryStore, archive_path: Path) -> dict:
    companies = [c for c in store.companies() if c.cik and c.cik.strip()]
    if not companies:
        raise ValueError("load a company universe with SEC CIKs first")
    found = 0
    missing_cik = []
    with zipfile.ZipFile(archive_path) as archive:
        names = {Path(name).name: name for name in archive.namelist() if name.endswith(".json")}
        for company in companies:
            member = names.get(f"CIK{int(company.cik):010d}.json")
            if not member:
                missing_cik.append(company.cik)
                continue
            data = json.loads(archive.read(member))
            found += _ingest_sec_data(store, company, data)
        store.commit()
    return {"companies": len(companies), "candidate_filings": found,
            "ciks_missing_from_bulk": missing_cik}


async def discover_sec_history(
    store: DiscoveryStore, archive_path: Path, cache_root: Path,
    user_agent: str, *, workers: int = 8,
) -> dict:
    """Fetch only referenced SEC history files needed for missing fiscal years."""
    tasks: list[tuple[Company, str]] = []
    with zipfile.ZipFile(archive_path) as archive:
        names = {Path(name).name: name for name in archive.namelist() if name.endswith(".json")}
        for company in [c for c in store.companies() if c.cik and c.cik.strip()]:
            member = names.get(f"CIK{int(company.cik):010d}.json")
            if not member:
                continue
            present = {row[0] for row in store.connection.execute(
                """SELECT DISTINCT report_year FROM candidates
                WHERE company_key=? AND source='SEC' AND status='DISCOVERED'""",
                (company.key,),
            )}
            missing = store.years(company.key) - present
            if not missing:
                continue
            data = json.loads(archive.read(member))
            for item in data.get("filings", {}).get("files", []):
                name = item.get("name", "")
                if not re.fullmatch(r"CIK\d{10}-submissions-\d{3}\.json", name):
                    continue
                first = str(item.get("filingFrom", ""))[:4]
                last = str(item.get("filingTo", ""))[:4]
                if not (first.isdigit() and last.isdigit()):
                    continue
                if int(last) < min(missing) or int(first) > max(missing) + 2:
                    continue
                tasks.append((company, name))
    if not tasks:
        return {"history_files": 0, "candidate_filings": 0, "errors": []}
    cache_root.mkdir(parents=True, exist_ok=True)
    if any(not (cache_root / name).is_file() for _, name in tasks) and (not user_agent or "@" not in user_agent):
        raise ValueError("SEC_USER_AGENT must contain an organization and contact email for uncached history")
    gate = RateGate(SEC_REQUEST_INTERVAL_S)
    queue: asyncio.Queue[tuple[Company, str]] = asyncio.Queue()
    for item in tasks:
        queue.put_nowait(item)
    found = 0
    errors: list[str] = []
    timeout = httpx.Timeout(connect=10, read=90, write=30, pool=30)
    async with httpx.AsyncClient(timeout=timeout,
                                 limits=httpx.Limits(max_connections=workers, max_keepalive_connections=workers),
                                 headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}) as client:
        async def worker() -> None:
            nonlocal found
            while True:
                try:
                    company, name = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                cache_file = cache_root / name
                try:
                    if cache_file.is_file():
                        data = json.loads(cache_file.read_text(encoding="utf-8"))
                    else:
                        await gate.wait()
                        response = await client.get(f"https://data.sec.gov/submissions/{name}")
                        response.raise_for_status()
                        data = response.json()
                        staged = cache_file.with_suffix(".json.part")
                        staged.write_text(json.dumps(data), encoding="utf-8")
                        staged.replace(cache_file)
                    found += _ingest_sec_data(store, company, data)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
                finally:
                    queue.task_done()

        await asyncio.gather(*(worker() for _ in range(min(workers, len(tasks)))))
    store.commit()
    return {"history_files": len(tasks), "candidate_filings": found, "errors": errors}


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _pick(row: dict[str, str], *names: str) -> str:
    return next((row[name] for name in names if row.get(name)), "").strip()


def import_fca_csv(store: DiscoveryStore, csv_path: Path) -> dict:
    companies = {company.lei: company for company in store.companies("GBR")}
    if not companies:
        raise ValueError("load a UK company universe first")
    accepted = 0
    unmatched = 0
    review = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("FCA CSV has no header")
        for source_row in reader:
            row = {_normalize_header(key): (value or "") for key, value in source_row.items() if key}
            category = _pick(row, "category", "documentcategory", "informationtype")
            if category.casefold() != "annual financial report":
                continue
            lei = _pick(row, "disclosingorganisationlei", "organisationlei", "companylei", "lei").upper()
            company = companies.get(lei)
            if not company:
                unmatched += 1
                continue
            raw_link = _pick(row, "downloadlink", "downloadurl", "documentdownloadlink", "url", "link")
            if not raw_link:
                review += 1
                continue
            url = urljoin(FCA_BASE, raw_link)
            if urlsplit(url).scheme != "https":
                review += 1
                continue
            description = _pick(row, "description", "documentdescription", "documenttitle", "title")
            filename = _pick(row, "filename", "documentfilename")
            matches = set(YEAR_PATTERN.findall(description + " " + filename))
            year = int(next(iter(matches))) if len(matches) == 1 else None
            if year not in store.years(company.key):
                year = None
            suffix = Path(urlsplit(url).path).suffix.lower()
            source_format = "pdf" if suffix == ".pdf" or filename.lower().endswith(".pdf") else "zip" if suffix == ".zip" or filename.lower().endswith(".zip") else "html" if suffix in {".htm", ".html", ".xhtml"} else "unknown"
            source_record_id = _pick(row, "documentid", "id", "reference") or hashlib.sha256(url.encode()).hexdigest()
            status = "DISCOVERED" if year is not None and source_format == "pdf" else "MANUAL_REVIEW"
            store.upsert_candidate(
                company_key=company.key, report_year=year, source="FCA_NSM",
                source_record_id=source_record_id, source_url=url,
                source_format=source_format, form_type="AFR",
                publication_date=_pick(row, "publicationdate", "publicationdatetime"),
                filing_date=_pick(row, "filingdate", "filingdatetime"),
                report_date=_pick(row, "documentdate"), description=description,
                status=status, verified=status == "DISCOVERED",
                metadata={"raw_download_link": raw_link, "raw": source_row},
            )
            accepted += 1
            review += status == "MANUAL_REVIEW"
    store.commit()
    return {"candidate_records": accepted, "unmatched_lei": unmatched, "manual_review": review}


def import_fca_historic_map(store: DiscoveryStore, archive_path: Path,
                            *, import_all: bool = False) -> dict:
    """Stream FCA's large 2017-2020 ZIP; default to URLs already in the catalog."""
    needed = {row[0] for row in store.connection.execute(
        "SELECT DISTINCT source_url FROM candidates WHERE source_url LIKE '%morningstar.co.uk%'"
    )}
    if not import_all and not needed:
        return {"mappings_ingested": 0, "candidates_resolved": 0,
                "note": "no historic Morningstar URLs in the candidate catalog"}
    ingested = 0
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            if not (name.endswith(".csv") and ("20170101" in name or "20190101" in name)):
                continue
            with archive.open(name) as binary:
                reader = csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8-sig", errors="replace", newline=""))
                for row in reader:
                    old = (row.get("Morningstar URL") or "").strip()
                    new = (row.get("FCA URL") or "").strip()
                    if not new.startswith("https://data.fca.org.uk/"):
                        continue
                    if not import_all and old not in needed:
                        continue
                    store.connection.execute(
                        """INSERT OR REPLACE INTO fca_historic_url_map
                        VALUES (?,?,?,?,?,?)""",
                        (old, new, name, (row.get("Company Name") or "").strip(),
                         (row.get("Title") or "").strip(),
                         (row.get("Published Date") or "").strip()),
                    )
                    ingested += 1
                    if ingested % 5000 == 0:
                        store.commit()
    store.connection.execute(
        """UPDATE candidates SET source_url=(
            SELECT m.fca_url FROM fca_historic_url_map m
            WHERE m.old_nsm_url=candidates.source_url),
            source_format='pdf',
            status=CASE WHEN report_year IS NOT NULL THEN 'DISCOVERED' ELSE status END,
            verified=CASE WHEN report_year IS NOT NULL THEN 1 ELSE verified END
        WHERE source_url IN (SELECT old_nsm_url FROM fca_historic_url_map)"""
    )
    resolved = store.connection.execute("SELECT changes()").fetchone()[0]
    store.commit()
    return {"mappings_ingested": ingested, "candidates_resolved": resolved}


def export_pdf_manifest(store: DiscoveryStore, path: Path) -> dict:
    rows = []
    non_pdf = 0
    duplicates = 0
    seen: set[tuple[str, int]] = set()
    query = """SELECT c.*, u.country, u.exchange, u.lei, u.isin, u.ticker
               FROM candidates c JOIN companies u USING(company_key)
               WHERE c.verified=1 AND c.report_year IS NOT NULL
                 AND c.status='DISCOVERED'
               ORDER BY c.company_key, c.report_year, c.filing_date, c.id"""
    for item in store.connection.execute(query):
        if item["source_format"] != "pdf":
            non_pdf += 1
            continue
        identity = (item["company_key"], item["report_year"])
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        report_type = {"10-K": "10K", "20-F": "20F"}.get(item["form_type"], "AR")
        rows.append({"country": item["country"], "exchange": item["exchange"],
                     "lei": item["lei"], "isin": item["isin"],
                     "ticker": item["ticker"], "fiscal_year": f"FY{item['report_year']}",
                     "report_type": report_type, "language": "EN",
                     "pdf_url": item["source_url"], "source_page": "", "verified": "true"})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("country", "exchange", "lei", "isin", "ticker",
                                                   "fiscal_year", "report_type", "language",
                                                   "pdf_url", "source_page", "verified"))
        writer.writeheader()
        writer.writerows(rows)
    return {"pdf_rows": len(rows), "non_pdf_candidates": non_pdf,
            "extra_candidates_same_company_year": duplicates, "output": str(path)}
