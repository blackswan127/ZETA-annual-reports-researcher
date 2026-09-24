"""High-speed persistent index and autonomous discovery for FCA NSM filings."""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from .discovery import DiscoveryStore

YEAR_PATTERN = re.compile(r"\b(19\d\d|20\d\d)\b")
NON_WORD_PATTERN = re.compile(r"[^\w\s]")


def clean_company_name(name: str) -> str:
    """Normalize company name for robust fuzzy/lexical matching."""
    s = NON_WORD_PATTERN.sub(" ", name).upper()
    tokens = [
        t for t in s.split()
        if t not in {"PLC", "PUBLIC", "LIMITED", "LTD", "GROUP", "HOLDINGS", "CORP", "CORPORATION", "THE"}
    ]
    return " ".join(tokens)


def _extract_year(title: str, pub_date: str) -> int | None:
    # First search title
    title_matches = YEAR_PATTERN.findall(title)
    if title_matches:
        y = int(title_matches[-1])
        if 1990 <= y <= 2030:
            return y
    # Fallback to published date
    date_matches = YEAR_PATTERN.findall(pub_date)
    if date_matches:
        y = int(date_matches[0])
        if 1990 <= y <= 2030:
            return y
    return None


def _is_annual_report(title: str) -> bool:
    tl = title.lower()
    if (
        "half" in tl or "interim" in tl or "quarter" in tl or "proxy" in tl
        or "notice" in tl or "agm" in tl or "result of" in tl or "award" in tl
        or "statement" in tl or "availability" in tl or "convening" in tl
    ):
        return False
    return "annual" in tl or "accounts" in tl or "financial report" in tl or "report and accounts" in tl


def build_or_open_fca_catalog(cache_dir: Path, archive_path: Path | None = None) -> sqlite3.Connection:
    """Opens or builds an indexed SQLite catalog of FCA NSM filings from mapping.zip."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    db_path = cache_dir / "fca_catalog.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS fca_nsm_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            clean_name TEXT NOT NULL,
            title TEXT NOT NULL,
            published_date TEXT,
            year INTEGER,
            fca_url TEXT NOT NULL UNIQUE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fca_clean_name ON fca_nsm_catalog(clean_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fca_year ON fca_nsm_catalog(year)")
    conn.commit()

    # Check if empty
    count = conn.execute("SELECT COUNT(*) FROM fca_nsm_catalog").fetchone()[0]
    if count == 0 and archive_path and archive_path.is_file():
        # Populate from archive
        batch = []
        seen_urls = set()
        with zipfile.ZipFile(archive_path) as z:
            for name in z.namelist():
                if not name.endswith(".csv"):
                    continue
                with z.open(name) as f:
                    reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="ignore"))
                    try:
                        header = next(reader)
                    except StopIteration:
                        continue
                    for row in reader:
                        if len(row) < 5:
                            continue
                        c_name, title, dt, _, fca_url = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip(), row[4].strip()
                        if not fca_url.startswith("https://data.fca.org.uk/") or fca_url in seen_urls:
                            continue
                        if not _is_annual_report(title):
                            continue
                        seen_urls.add(fca_url)
                        year = _extract_year(title, dt)
                        clean = clean_company_name(c_name)
                        batch.append((c_name, clean, title, dt, year, fca_url))

                        if len(batch) >= 5000:
                            conn.executemany("""
                                INSERT OR IGNORE INTO fca_nsm_catalog
                                (company_name, clean_name, title, published_date, year, fca_url)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, batch)
                            conn.commit()
                            batch = []

        if batch:
            conn.executemany("""
                INSERT OR IGNORE INTO fca_nsm_catalog
                (company_name, clean_name, title, published_date, year, fca_url)
                VALUES (?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()

    return conn


def query_fca_catalog(
    conn: sqlite3.Connection,
    company_name: str,
    ticker: str = "",
    years: list[int] | None = None,
) -> list[dict]:
    """Queries filings for a company by clean name or exact match, filtered by year."""
    clean = clean_company_name(company_name)
    if not clean:
        return []

    query = """
        SELECT company_name, clean_name, title, published_date, year, fca_url
        FROM fca_nsm_catalog
        WHERE (clean_name = ? OR clean_name LIKE ? OR company_name LIKE ?)
    """
    params = [clean, f"%{clean}%", f"%{company_name}%"]

    if years:
        placeholders = ",".join("?" for _ in years)
        query += f" AND year IN ({placeholders})"
        params.extend(years)

    query += " ORDER BY year DESC, (CASE WHEN fca_url LIKE '%.pdf' THEN 0 ELSE 1 END), id DESC"
    cursor = conn.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def discover_fca_candidates(
    store: DiscoveryStore,
    catalog_conn: sqlite3.Connection,
    company_keys: set[str] | None = None,
) -> dict:
    """Discovers FCA NSM annual reports for UK companies in store and records candidates."""
    companies = store.companies("GBR")
    discovered = 0

    for company in companies:
        if company_keys and company.key not in company_keys:
            continue
        expected_years = store.years(company.key)
        if not expected_years:
            continue

        names_to_try = [company.company_name]
        if company.aliases:
            for a in re.split(r"[;,]", company.aliases):
                a_clean = a.strip()
                if a_clean and a_clean not in names_to_try:
                    names_to_try.append(a_clean)

        results = []
        for n in names_to_try:
            results = query_fca_catalog(catalog_conn, n, company.ticker, list(expected_years))
            if results:
                break
        seen_years = set()

        for item in results:
            y = item["year"]
            if y is None or y in seen_years:
                continue
            seen_years.add(y)

            url = item["fca_url"]
            source_format = "pdf" if url.endswith(".pdf") else "html"
            record_id = urlsplit(url).path.split("/")[-1].split(".")[0]

            store.upsert_candidate(
                company_key=company.key,
                report_year=y,
                source="FCA_NSM",
                source_record_id=record_id,
                source_url=url,
                source_format=source_format,
                form_type="AFR",
                publication_date=item.get("published_date", ""),
                description=item.get("title", ""),
                status="DISCOVERED" if source_format == "pdf" else "MANUAL_REVIEW",
                verified=(source_format == "pdf"),
                metadata={"fca_raw_title": item.get("title", "")},
            )
            discovered += 1

    store.commit()
    return {"candidates_discovered": discovered}
