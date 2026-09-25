from __future__ import annotations

import asyncio
import httpx
import json
import os
import re
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .contract import (
    CandidateFiling,
    CohortManifest,
    CurrentIssuerRecord,
    SlotResult,
    resolve_market_info,
)
from .promotion import (
    compute_sha256_and_size,
    promote_pdf_to_corpus,
    validate_pdf_bytes_or_file,
)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def ensure_sys_paths():
    paths = [
        str(ROOT_DIR / "markets" / "Australia" / "src"),
        str(ROOT_DIR / "markets" / "Bangladesh" / "src"),
        str(ROOT_DIR / "markets" / "Canada" / "src"),
        str(ROOT_DIR / "markets" / "HongKong"),
        str(ROOT_DIR / "markets" / "India" / "src"),
        str(ROOT_DIR / "markets" / "NewZealand" / "src"),
        str(ROOT_DIR / "markets" / "Singapore" / "src"),
        str(ROOT_DIR / "markets" / "SriLanka" / "src"),
        str(ROOT_DIR / "markets" / "Africa" / "src"),
    ]
    for p in paths:
        if p not in sys.path:
            sys.path.insert(0, p)


ensure_sys_paths()


class BaseMarketAdapter(ABC):
    def __init__(self, market_name: str):
        self.market_name = market_name
        self.info = resolve_market_info(market_name)
        self.local_dir = ROOT_DIR / "local" / "markets" / self.info["name"]
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir = self.local_dir / "staging"
        self.manifest_dir = self.local_dir / "manifests"
        self.manifest_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        """Fetch or load the active current issuer roster."""
        pass

    @abstractmethod
    async def harvest_cohort(
        self,
        cohort: CohortManifest,
        output_corpus: Path,
    ) -> List[SlotResult]:
        """Execute discovery, downloading, and SOP promotion for the given cohort."""
        pass


class AustraliaAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("Australia")
        self._lei_cache = None
        self._isin_cache = None

    def _load_mappings(self) -> tuple[dict[str, str], dict[str, str]]:
        if self._lei_cache is not None and self._isin_cache is not None:
            return self._lei_cache, self._isin_cache
        ticker_to_lei: dict[str, str] = {}
        ticker_to_isin: dict[str, str] = {}
        for p in (ROOT_DIR / "local").glob("wikidata*.json"):
            try:
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        for item in data:
                            t = item.get("ticker", "")
                            isin = item.get("isin", "")
                            lei = item.get("lei", "")
                            if isinstance(t, dict): t = t.get("value", "")
                            if isinstance(isin, dict): isin = isin.get("value", "")
                            if isinstance(lei, dict): lei = lei.get("value", "")
                            t = str(t).strip().upper()
                            isin = str(isin).strip().upper()
                            lei = str(lei).strip().upper()
                            if t and lei and len(lei) == 20:
                                ticker_to_lei[t] = lei
                            if t and isin and len(isin) == 12:
                                ticker_to_isin[t] = isin
            except Exception:
                pass
        self._lei_cache = ticker_to_lei
        self._isin_cache = ticker_to_isin
        return ticker_to_lei, ticker_to_isin

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from asx_bulk.source import ASXSource
        source = ASXSource(timeout=30.0, retries=3, metadata_rps=3.0)
        try:
            records = await source.current_issuers()
        finally:
            await source.close()

        ticker_to_lei, ticker_to_isin = self._load_mappings()
        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        roster = []
        for r in records:
            ticker = r.ticker.strip().upper()
            lei = ticker_to_lei.get(ticker, "")
            isin = ticker_to_isin.get(ticker, "")
            roster.append(CurrentIssuerRecord(
                issuer_id=ticker,
                legal_name=r.name,
                country_iso3="AUS",
                mic="XASX",
                ticker=ticker,
                isin=isin,
                lei=lei,
                instrument_type="Equity",
                active_status="ACTIVE",
                as_of_date=as_of,
                source_url="https://www.asx.com.au/asx/research/ASXListedCompanies.csv",
            ))
        return roster

    async def harvest_cohort(
        self,
        cohort: CohortManifest,
        output_corpus: Path,
    ) -> List[SlotResult]:
        ensure_sys_paths()
        from asx_bulk.config import Settings
        from asx_bulk.pipeline import Pipeline

        os.environ["ASX_ACKNOWLEDGE_TERMS"] = "1"
        work_dir = self.local_dir / "work"
        start_yr = min(cohort.fiscal_years) if cohort.fiscal_years else 2017
        end_yr = max(cohort.fiscal_years) if cohort.fiscal_years else 2025

        settings = Settings(
            output_dir=work_dir,
            start_year=start_yr,
            end_year=end_yr,
            metadata_workers=8,
            metadata_rps=3.0,
            download_workers=6,
            download_rps=3.0,
        )
        pipe = Pipeline(settings)
        tickers = [i.ticker for i in cohort.issuers]
        t0 = time.time()

        try:
            await pipe.discover(tickers=tickers, force=False)
            await pipe.download(tickers=tickers)
        finally:
            pass

        results: List[SlotResult] = []
        for issuer in cohort.issuers:
            for fy in cohort.fiscal_years:
                company_pattern = f"{issuer.ticker}_*"
                fy_dir = work_dir / "pdfs"
                matched_pdfs = []
                if fy_dir.exists():
                    for f in fy_dir.glob(f"{company_pattern}/{fy}/*.pdf"):
                        matched_pdfs.append(f)
                    if not matched_pdfs:
                        for f in fy_dir.glob(f"{issuer.ticker}*/**/{fy}/*.pdf"):
                            matched_pdfs.append(f)

                if matched_pdfs:
                    for matched_pdf in matched_pdfs:
                        fname_lower = matched_pdf.name.lower()
                        if "annual" in fname_lower:
                            rep_type = "AR"
                        elif "sustain" in fname_lower or "sr" in fname_lower:
                            rep_type = "SR"
                        elif "esg" in fname_lower:
                            rep_type = "ESG"
                        elif "climate" in fname_lower:
                            rep_type = "CLIMATE"
                        else:
                            rep_type = "AR"

                        slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}:{rep_type}"
                        status, reason, final_path = promote_pdf_to_corpus(
                            source_pdf=matched_pdf,
                            output_root=output_corpus,
                            staging_root=self.staging_dir,
                            iso3=issuer.country_iso3,
                            mic=issuer.mic,
                            ticker=issuer.ticker,
                            fiscal_year=fy,
                            lei=issuer.lei,
                            isin=issuer.isin,
                            report_type=rep_type,
                        )
                        h, sz = compute_sha256_and_size(final_path if final_path.exists() else matched_pdf)
                        _, pages, _ = validate_pdf_bytes_or_file(final_path if final_path.exists() else matched_pdf)
                        results.append(SlotResult(
                            slot_id=slot_id,
                            run_id=cohort.run_id,
                            issuer_id=issuer.issuer_id,
                            fiscal_year=fy,
                            status=status,
                            reason=reason,
                            sha256=h,
                            page_count=pages,
                            file_size_bytes=sz,
                            destination_path=str(final_path),
                            elapsed_seconds=round(time.time() - t0, 2),
                        ))
                else:
                    slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}:AR"
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="UNRESOLVED",
                        reason="No candidate filing found or download incomplete",
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
        return results


class IndiaAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("India")

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from india_ar_bulk.source import BSESource, current_india_universe
        os.environ["INDIA_AR_ACKNOWLEDGE_TERMS"] = "1"
        b = BSESource(timeout=30.0, retries=3, rps=3.0)
        try:
            issuers, stats = await current_india_universe(b, include_sme=True)
        finally:
            await b.close()

        if not issuers:
            # Check seed template roster
            csv_path = ROOT_DIR / "markets" / "India" / "templates" / "current_universe.csv"
            if csv_path.exists():
                import csv
                with open(csv_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    from india_ar_bulk.models import Issuer
                    issuers = [
                        Issuer(
                            issuer_key=r["isin"] or r["ticker"],
                            isin=r.get("isin", ""),
                            name=r.get("name", r["ticker"]),
                            nse_symbol=r.get("nse_symbol", r["ticker"]),
                            bse_scrip=r.get("bse_scrip", ""),
                            nse_series="EQ",
                            nse_sme=False,
                            bse_group="A",
                            source_flags="SEED_UNIVERSE",
                        )
                        for r in reader
                    ]

        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        roster = []
        for i in issuers:
            roster.append(CurrentIssuerRecord(
                issuer_id=i.issuer_key,
                legal_name=i.name,
                country_iso3="IND",
                mic="XBOM" if i.bse_scrip else "XNSE",
                ticker=i.bse_scrip or i.nse_symbol,
                isin=i.isin,
                instrument_type="Equity",
                active_status="ACTIVE",
                as_of_date=as_of,
                secondary_mic="XNSE" if (i.nse_symbol and i.bse_scrip) else "",
                secondary_ticker=i.nse_symbol if i.bse_scrip else "",
            ))
        return roster

    async def harvest_cohort(
        self,
        cohort: CohortManifest,
        output_corpus: Path,
    ) -> List[SlotResult]:
        ensure_sys_paths()
        from india_ar_bulk.config import Settings
        from india_ar_bulk.pipeline import Pipeline

        os.environ["INDIA_AR_ACKNOWLEDGE_TERMS"] = "1"
        work_dir = self.local_dir / "work"
        start_yr = min(cohort.fiscal_years) if cohort.fiscal_years else 2017
        end_yr = max(cohort.fiscal_years) if cohort.fiscal_years else 2025

        settings = Settings(
            output_dir=work_dir,
            start_year=start_yr,
            end_year=end_yr,
            metadata_workers=6,
            bse_rps=3.0,
            download_workers=8,
            download_rps=4.0,
            timeout=45.0,
            retries=5,
        )

        pipe = Pipeline(settings)
        t0 = time.time()
        isins = [i.isin for i in cohort.issuers if i.isin]
        keys = [i.issuer_id for i in cohort.issuers]

        try:
            await pipe.discover(force=False)
            await pipe.download(isins=isins, keys=keys)
        finally:
            pipe.close()

        results: List[SlotResult] = []
        for issuer in cohort.issuers:
            for fy in cohort.fiscal_years:
                slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}"
                matched_pdf = None
                key = issuer.isin or issuer.ticker or issuer.issuer_id
                fy_dir = work_dir / "pdfs"
                if fy_dir.exists():
                    for f in fy_dir.glob(f"*{key}*/**/{fy}/*.pdf"):
                        matched_pdf = f
                        break

                if matched_pdf and matched_pdf.exists():
                    status, reason, final_path = promote_pdf_to_corpus(
                        source_pdf=matched_pdf,
                        output_root=output_corpus,
                        staging_root=self.staging_dir,
                        iso3=issuer.country_iso3,
                        mic=issuer.mic,
                        ticker=issuer.ticker,
                        fiscal_year=fy,
                        lei=issuer.lei,
                        isin=issuer.isin,
                    )
                    h, sz = compute_sha256_and_size(final_path if final_path.exists() else matched_pdf)
                    _, pages, _ = validate_pdf_bytes_or_file(final_path if final_path.exists() else matched_pdf)
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status=status,
                        reason=reason,
                        sha256=h,
                        page_count=pages,
                        file_size_bytes=sz,
                        destination_path=str(final_path),
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
                else:
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="UNRESOLVED",
                        reason="No candidate filing found or download incomplete",
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
        return results


class HongKongAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("HongKong")

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from hkex_bulk.hkex import HKEXClient
        from hkex_bulk.pipeline import refresh_active
        from hkex_bulk.db import Database

        db_path = self.local_dir / "manifest.sqlite3"
        db = Database(db_path)
        async with HKEXClient(timeout=30.0, max_retries=3, metadata_rps=2.5, download_rps=8.0) as client:
            await refresh_active(db, client)

        rows = db.conn.execute("SELECT DISTINCT code, name_en, hkex_id FROM active_securities ORDER BY code").fetchall()
        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        roster = []
        for r in rows:
            code = str(r["code"]).zfill(5)
            roster.append(CurrentIssuerRecord(
                issuer_id=code,
                legal_name=r["name_en"],
                country_iso3="HKG",
                mic="XHKG",
                ticker=code,
                instrument_type="Equity",
                active_status="ACTIVE",
                as_of_date=as_of,
                source_url="https://www.hkexnews.hk/sdw/search/activestock_sehk_e.json",
            ))
        return roster

    async def harvest_cohort(
        self,
        cohort: CohortManifest,
        output_corpus: Path,
    ) -> List[SlotResult]:
        ensure_sys_paths()
        from hkex_bulk.db import Database
        from hkex_bulk.hkex import HKEXClient
        from hkex_bulk.pipeline import discover, download_selected

        work_dir = self.local_dir / "work"
        work_dir.mkdir(parents=True, exist_ok=True)
        db = Database(self.local_dir / "manifest.sqlite3")
        codes = [i.ticker.zfill(5) for i in cohort.issuers]
        start_yr = min(cohort.fiscal_years) if cohort.fiscal_years else 2017
        end_yr = max(cohort.fiscal_years) if cohort.fiscal_years else 2025
        t0 = time.time()

        async with HKEXClient(timeout=45.0, max_retries=5, metadata_rps=2.5, download_rps=8.0) as client:
            await discover(db, client, start_year=start_yr, end_year=end_yr)
            await download_selected(db, client, output=work_dir, workers=8, stock_codes=codes)

        results: List[SlotResult] = []
        for issuer in cohort.issuers:
            for fy in cohort.fiscal_years:
                slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}"
                matched_pdf = None
                code = issuer.ticker.zfill(5)
                for f in work_dir.glob(f"pdf/*{code}*/**/{fy}/*.pdf"):
                    matched_pdf = f
                    break

                if matched_pdf and matched_pdf.exists():
                    status, reason, final_path = promote_pdf_to_corpus(
                        source_pdf=matched_pdf,
                        output_root=output_corpus,
                        staging_root=self.staging_dir,
                        iso3=issuer.country_iso3,
                        mic=issuer.mic,
                        ticker=issuer.ticker,
                        fiscal_year=fy,
                        lei=issuer.lei,
                        isin=issuer.isin,
                    )
                    h, sz = compute_sha256_and_size(final_path if final_path.exists() else matched_pdf)
                    _, pages, _ = validate_pdf_bytes_or_file(final_path if final_path.exists() else matched_pdf)
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status=status,
                        reason=reason,
                        sha256=h,
                        page_count=pages,
                        file_size_bytes=sz,
                        destination_path=str(final_path),
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
                else:
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="UNRESOLVED",
                        reason="No candidate filing found or download incomplete",
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
        return results


class SingaporeAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("Singapore")

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from sgx_bulk.httpclient import RetryingClient
        from sgx_bulk.sgx import SGXSource

        http = RetryingClient(timeout=30, retries=2)
        source = SGXSource(http)
        try:
            issuers = await source.current_issuers()
        finally:
            await http.close()

        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        roster = []
        for i in issuers:
            roster.append(CurrentIssuerRecord(
                issuer_id=i.ibm_code,
                legal_name=i.issuer_name,
                country_iso3="SGP",
                mic="XSES",
                ticker=i.stock_code or i.ibm_code,
                isin=getattr(i, "isin", ""),
                instrument_type=getattr(i, "market", "Mainboard") or "Equity",
                active_status="ACTIVE",
                as_of_date=as_of,
                source_url="https://api.sgx.com/financialreports/v1.0",
                extra={"short_name": i.short_name, "ibm_code": i.ibm_code},
            ))
        return roster

    async def harvest_cohort(
        self,
        cohort: CohortManifest,
        output_corpus: Path,
    ) -> List[SlotResult]:
        ensure_sys_paths()
        from sgx_bulk.pipeline import Pipeline

        work_dir = self.local_dir / "work"
        start_yr = min(cohort.fiscal_years) if cohort.fiscal_years else 2017
        end_yr = max(cohort.fiscal_years) if cohort.fiscal_years else 2025
        pipe = Pipeline(
            work_dir, start_yr, end_yr,
            discovery_workers=6, detail_workers=8, download_workers=6, targeted_recovery=True,
        )
        t0 = time.time()
        ibm_codes = [i.issuer_id for i in cohort.issuers]
        stock_codes = [i.ticker for i in cohort.issuers]

        try:
            await pipe.discover()
            await pipe.resolve()
            await pipe.download(ibm_codes=ibm_codes, stock_codes=stock_codes)
        finally:
            await pipe.close()

        results: List[SlotResult] = []
        conn = pipe.db.conn
        for issuer in cohort.issuers:
            for fy in cohort.fiscal_years:
                downloaded_rows = conn.execute(
                    """SELECT a.local_path, f.report_type, f.title
                       FROM attachments a JOIN filings f USING(announcement_id)
                       WHERE f.ibm_code=? AND f.fiscal_year=? AND a.selected=1 AND a.status='done'""",
                    (issuer.issuer_id, fy),
                ).fetchall()

                if downloaded_rows:
                    for row in downloaded_rows:
                        local_p = Path(row[0]) if row[0] else None
                        rtype = row[1] if row[1] else "AR"
                        slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}:{rtype}"
                        if local_p and local_p.exists():
                            status, reason, final_path = promote_pdf_to_corpus(
                                source_pdf=local_p,
                                output_root=output_corpus,
                                staging_root=self.staging_dir,
                                iso3=issuer.country_iso3,
                                mic=issuer.mic,
                                ticker=issuer.ticker,
                                fiscal_year=fy,
                                lei=issuer.lei,
                                isin=issuer.isin,
                                report_type=rtype,
                            )
                            h, sz = compute_sha256_and_size(final_path if final_path.exists() else local_p)
                            _, pages, _ = validate_pdf_bytes_or_file(final_path if final_path.exists() else local_p)
                            results.append(SlotResult(
                                slot_id=slot_id,
                                run_id=cohort.run_id,
                                issuer_id=issuer.issuer_id,
                                fiscal_year=fy,
                                status=status,
                                reason=reason,
                                sha256=h,
                                page_count=pages,
                                file_size_bytes=sz,
                                destination_path=str(final_path),
                                elapsed_seconds=round(time.time() - t0, 2),
                            ))
                else:
                    slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}:AR"
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="UNRESOLVED",
                        reason="No candidate filing found or download incomplete",
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
        return results


class CanadaAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("Canada")

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from canada_zeta_bulk.universe import fetch_latest_tmx_list, parse_universe_file
        os.environ["CANADA_AR_ACKNOWLEDGE_TMX_TERMS"] = "1"
        cached_xlsx = ROOT_DIR / "markets" / "Canada" / "input" / "tmx_current.xlsx"
        issuers = []
        if cached_xlsx.exists() and not refresh:
            try:
                issuers = parse_universe_file(cached_xlsx, include_nex=False)
            except Exception:
                issuers = []
        if not issuers:
            try:
                issuers, _ = await fetch_latest_tmx_list(45.0, include_nex=False)
            except Exception:
                example_csv = ROOT_DIR / "markets" / "Canada" / "input" / "tmx_current_list.example.csv"
                if example_csv.exists():
                    issuers = parse_universe_file(example_csv, include_nex=False)


        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        roster = []
        for i in issuers:
            roster.append(CurrentIssuerRecord(
                issuer_id=i.issuer_key,
                legal_name=i.name,
                country_iso3="CAN",
                mic=i.exchange_mic or "XTSE",
                ticker=i.ticker,
                isin=i.isin,
                lei=i.lei,
                instrument_type=i.security_type or "Equity",
                active_status="ACTIVE",
                as_of_date=as_of,
                source_url=i.website or "https://www.tsx.com",
            ))
        return roster

    async def harvest_cohort(
        self,
        cohort: CohortManifest,
        output_corpus: Path,
    ) -> List[SlotResult]:
        ensure_sys_paths()
        from canada_zeta_bulk.config import Settings
        from canada_zeta_bulk.pipeline import Pipeline

        work_dir = self.local_dir / "work"
        start_yr = min(cohort.fiscal_years) if cohort.fiscal_years else 2017
        end_yr = max(cohort.fiscal_years) if cohort.fiscal_years else 2025
        settings = Settings(
            work_dir=work_dir,
            zeta_root=output_corpus,
            start_year=start_yr,
            end_year=end_yr,
        )
        pipe = Pipeline(settings)
        t0 = time.time()
        keys = [i.issuer_id for i in cohort.issuers]
        tickers = [i.ticker for i in cohort.issuers]

        try:
            await pipe.discover_issuer_sites(limit=len(keys))
            pipe.resolve()
            await pipe.download(keys=keys, tickers=tickers)
            pipe.finalize_staging()
        finally:
            pipe.close()

        results: List[SlotResult] = []
        for issuer in cohort.issuers:
            for fy in cohort.fiscal_years:
                slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}"
                matched_pdf = None
                # Check directly in output corpus or staging
                for f in output_corpus.glob(f"CAN/**/{issuer.ticker}*/**/FY{fy}/*.pdf"):
                    matched_pdf = f
                    break
                if not matched_pdf:
                    for f in self.staging_dir.glob(f"**/{issuer.ticker}*/**/FY{fy}/*.pdf"):
                        matched_pdf = f
                        break

                if matched_pdf and matched_pdf.exists():
                    h, sz = compute_sha256_and_size(matched_pdf)
                    _, pages, _ = validate_pdf_bytes_or_file(matched_pdf)
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="PROMOTED" if output_corpus in matched_pdf.parents else "STAGED_UNRESOLVED_IDENTITY",
                        reason="Validated",
                        sha256=h,
                        page_count=pages,
                        file_size_bytes=sz,
                        destination_path=str(matched_pdf),
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
                else:
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="UNRESOLVED",
                        reason="No candidate filing found or download incomplete",
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
        return results


class BangladeshAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("Bangladesh")

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from dse_zeta.config import RuntimeConfig
        from dse_zeta.http import Http
        from dse_zeta.sources.dse_public import DSEPublic
        from dse_zeta.identity import load_universe_csv

        os.environ["DSE_ACKNOWLEDGE_TERMS"] = "1"
        u_csv = ROOT_DIR / "markets" / "Bangladesh" / "templates" / "current_universe.csv"
        if u_csv.exists():
            issuers = load_universe_csv(u_csv)
        else:
            cfg = RuntimeConfig(2017, 2025, 4, 6, 0.35, 45, 5, 8000)
            http = Http(cfg.request_delay, cfg.timeout, cfg.max_retries)
            try:
                issuers = DSEPublic(http).current_universe(1, 0, True, 4)
            finally:
                pass

        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        roster = []
        for i in issuers:
            roster.append(CurrentIssuerRecord(
                issuer_id=i.ticker,
                legal_name=i.name,
                country_iso3="BGD",
                mic="XDHA",
                ticker=i.ticker,
                isin=i.isin,
                lei=i.lei,
                instrument_type=i.instrument_type or "Equity",
                active_status="ACTIVE",
                as_of_date=as_of,
                source_url=i.website or "https://dse.ternary.com.bd",
            ))
        return roster

    async def harvest_cohort(
        self,
        cohort: CohortManifest,
        output_corpus: Path,
    ) -> List[SlotResult]:
        ensure_sys_paths()
        from dse_zeta.config import RuntimeConfig
        from dse_zeta.pipeline import Pipeline

        os.environ["DSE_ACKNOWLEDGE_TERMS"] = "1"
        work_dir = self.local_dir / "work"
        start_yr = min(cohort.fiscal_years) if cohort.fiscal_years else 2017
        end_yr = max(cohort.fiscal_years) if cohort.fiscal_years else 2025
        cfg = RuntimeConfig(start_yr, end_yr, 4, 6, 0.35, 45, 5, 8000)
        pipe = Pipeline(work_dir, output_corpus, cfg)
        t0 = time.time()
        tickers = [i.ticker for i in cohort.issuers]

        try:
            pipe.discover_financial_links()
            pipe.discover_ir_missing()
            pipe.download(tickers=tickers)
        finally:
            pipe.close()

        results: List[SlotResult] = []
        for issuer in cohort.issuers:
            for fy in cohort.fiscal_years:
                slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}"
                matched_pdf = None
                for f in output_corpus.glob(f"BGD/**/{issuer.ticker}*/**/FY{fy}/*.pdf"):
                    matched_pdf = f
                    break
                if not matched_pdf:
                    for f in (work_dir / "staging").glob(f"**/{issuer.ticker}*/**/FY{fy}/*.pdf"):
                        matched_pdf = f
                        break

                if matched_pdf and matched_pdf.exists():
                    h, sz = compute_sha256_and_size(matched_pdf)
                    _, pages, _ = validate_pdf_bytes_or_file(matched_pdf)
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="PROMOTED" if output_corpus in matched_pdf.parents else "STAGED_UNRESOLVED_IDENTITY",
                        reason="Validated",
                        sha256=h,
                        page_count=pages,
                        file_size_bytes=sz,
                        destination_path=str(matched_pdf),
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
                else:
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="UNRESOLVED",
                        reason="No candidate filing found or download incomplete",
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
        return results


class NewZealandAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("NewZealand")

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from nzx_zeta.config import RuntimeConfig
        from nzx_zeta.http import Http
        from nzx_zeta.sources.nzx_public import NZXPublic
        from nzx_zeta.identity import load_universe_csv

        os.environ["NZX_ACKNOWLEDGE_TERMS"] = "1"
        u_csv = ROOT_DIR / "markets" / "NewZealand" / "templates" / "current_universe.csv"
        if u_csv.exists():
            issuers = load_universe_csv(u_csv)
        else:
            cfg = RuntimeConfig(2017, 2025, 4, 6, 0.35, 45, 5, 8000)
            http = Http(cfg.request_delay, cfg.timeout, cfg.max_retries)
            try:
                issuers = NZXPublic(http).current_universe(1, 0)
            finally:
                pass

        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        roster = []
        for i in issuers:
            roster.append(CurrentIssuerRecord(
                issuer_id=i.ticker,
                legal_name=i.name,
                country_iso3="NZL",
                mic="XNZE",
                ticker=i.ticker,
                isin=i.isin,
                lei=i.lei,
                instrument_type=i.instrument_type or "Equity",
                active_status="ACTIVE",
                as_of_date=as_of,
                source_url=i.website or "https://www.nzx.com",
            ))
        return roster

    async def harvest_cohort(
        self,
        cohort: CohortManifest,
        output_corpus: Path,
    ) -> List[SlotResult]:
        ensure_sys_paths()
        from nzx_zeta.config import RuntimeConfig
        from nzx_zeta.pipeline import Pipeline

        os.environ["NZX_ACKNOWLEDGE_TERMS"] = "1"
        work_dir = self.local_dir / "work"
        start_yr = min(cohort.fiscal_years) if cohort.fiscal_years else 2017
        end_yr = max(cohort.fiscal_years) if cohort.fiscal_years else 2025
        cfg = RuntimeConfig(start_yr, end_yr, 4, 6, 0.35, 45, 5, 8000)
        pipe = Pipeline(work_dir, output_corpus, cfg)
        t0 = time.time()
        tickers = [i.ticker for i in cohort.issuers]

        try:
            pipe.discover_documents()
            pipe.discover_ir_missing()
            pipe.download(tickers=tickers)
        finally:
            pipe.close()

        results: List[SlotResult] = []
        for issuer in cohort.issuers:
            for fy in cohort.fiscal_years:
                slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}"
                matched_pdf = None
                for f in output_corpus.glob(f"NZL/**/{issuer.ticker}*/**/FY{fy}/*.pdf"):
                    matched_pdf = f
                    break
                if not matched_pdf:
                    for f in (work_dir / "staging").glob(f"**/{issuer.ticker}*/**/FY{fy}/*.pdf"):
                        matched_pdf = f
                        break

                if matched_pdf and matched_pdf.exists():
                    h, sz = compute_sha256_and_size(matched_pdf)
                    _, pages, _ = validate_pdf_bytes_or_file(matched_pdf)
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="PROMOTED" if output_corpus in matched_pdf.parents else "STAGED_UNRESOLVED_IDENTITY",
                        reason="Validated",
                        sha256=h,
                        page_count=pages,
                        file_size_bytes=sz,
                        destination_path=str(matched_pdf),
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
                else:
                    results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="UNRESOLVED",
                        reason="No candidate filing found or download incomplete",
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
        return results


class SriLankaAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("SriLanka")
        self._lei_cache = None
        self._isin_cache = None

    def _load_mappings(self) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        if self._lei_cache is not None and self._isin_cache is not None and hasattr(self, "_name_to_lei"):
            return self._lei_cache, self._isin_cache, self._name_to_lei
        ticker_to_lei: dict[str, str] = {}
        ticker_to_isin: dict[str, str] = {}
        name_to_lei: dict[str, str] = {}

        gleif_file = ROOT_DIR / "markets" / "SriLanka" / "local" / "gleif_lk.json"
        if gleif_file.exists():
            try:
                with open(gleif_file, encoding="utf-8") as fh:
                    gdata = json.load(fh)
                    for item in gdata:
                        lei = item.get("attributes", {}).get("lei", "")
                        name = item.get("attributes", {}).get("entity", {}).get("legalName", {}).get("name", "")
                        clean = re.sub(r"[^A-Z0-9]", "", name.upper()).replace("PLC", "").replace("LIMITED", "").replace("LTD", "").replace("PUBLIC", "")
                        if clean and lei and len(lei) == 20:
                            name_to_lei[clean] = lei
            except Exception:
                pass

        for p in (ROOT_DIR / "local").glob("wikidata*.json"):
            try:
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        for item in data:
                            t = item.get("ticker", "")
                            isin = item.get("isin", "")
                            lei = item.get("lei", "")
                            if isinstance(t, dict): t = t.get("value", "")
                            if isinstance(isin, dict): isin = isin.get("value", "")
                            if isinstance(lei, dict): lei = lei.get("value", "")
                            t = str(t).strip().upper()
                            isin = str(isin).strip().upper()
                            lei = str(lei).strip().upper()
                            if t and lei and len(lei) == 20:
                                ticker_to_lei[t] = lei
                            if t and isin and len(isin) == 12:
                                ticker_to_isin[t] = isin
            except Exception:
                pass

        self._lei_cache = ticker_to_lei
        self._isin_cache = ticker_to_isin
        self._name_to_lei = name_to_lei
        return self._lei_cache, self._isin_cache, self._name_to_lei

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from lka_cse_bulk.cse import CSEClient

        roster_cache = self.local_dir / "roster.json"
        if not refresh and roster_cache.exists():
            try:
                with open(roster_cache, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return [CurrentIssuerRecord.from_dict(d) for d in data]
            except Exception:
                pass

        lei_map, isin_map, name_to_lei = self._load_mappings()
        client = CSEClient()
        try:
            raw_issuers = await client.universe()
        finally:
            await client.close()

        # Enrich missing ISINs via companyInfoSummery concurrently
        missing_isin = [i for i in raw_issuers if not (i.isin or isin_map.get(i.ticker.upper()))]
        if missing_isin:
            sem = asyncio.Semaphore(16)
            async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as http_client:
                async def fetch_isin(iss):
                    async with sem:
                        try:
                            r = await http_client.post("https://www.cse.lk/api/companyInfoSummery", data={"symbol": iss.symbol}, timeout=10)
                            if r.status_code == 200:
                                val = r.json().get("reqSymbolInfo", {}).get("isin")
                                if val:
                                    isin_map[iss.ticker.upper()] = val
                        except Exception:
                            pass
                await asyncio.gather(*(fetch_isin(i) for i in missing_isin))

        roster: List[CurrentIssuerRecord] = []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for i in raw_issuers:
            tick = i.ticker.upper()
            clean_name = re.sub(r"[^A-Z0-9]", "", i.name.upper()).replace("PLC", "").replace("LIMITED", "").replace("LTD", "").replace("PUBLIC", "")
            lei = i.lei or lei_map.get(tick, "") or name_to_lei.get(clean_name, "")
            isin = i.isin or isin_map.get(tick, "")
            roster.append(CurrentIssuerRecord(
                issuer_id=i.symbol,
                legal_name=i.name,
                country_iso3="LKA",
                mic="XCOL",
                ticker=i.ticker,
                isin=isin,
                lei=lei,
                instrument_type="Equity",
                active_status="ACTIVE",
                as_of_date=today,
                source_url="https://www.cse.lk/api/alphabetical",
                extra={"symbol": i.symbol, "stable_id": i.issuer_id},
            ))

        with open(roster_cache, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in roster], f, indent=2)
        return roster

    async def harvest_cohort(
        self,
        cohort: CohortManifest,
        output_corpus: Path,
    ) -> List[SlotResult]:
        ensure_sys_paths()
        from lka_cse_bulk.cse import CSEClient, Issuer as CSEIssuer
        from lka_cse_bulk.downloader import Downloader

        work_dir = self.local_dir / "work"
        staging_dir = self.staging_dir
        work_dir.mkdir(parents=True, exist_ok=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        start_yr = min(cohort.fiscal_years) if cohort.fiscal_years else 2017
        end_yr = max(cohort.fiscal_years) if cohort.fiscal_years else 2025

        cse_client = CSEClient(rps=2.0)
        downloader = Downloader(workers=16, rps=8.0)

        results: List[SlotResult] = []
        sem = asyncio.Semaphore(8)

        async def process_issuer(issuer):
            symbol = issuer.extra.get("symbol") if hasattr(issuer, "extra") and isinstance(issuer.extra, dict) else ""
            if not symbol:
                symbol = f"{issuer.ticker}.N0000"
            cse_iss = CSEIssuer(
                issuer_id=f"LKA:XCOL:{issuer.ticker}",
                symbol=symbol,
                ticker=issuer.ticker,
                name=issuer.legal_name,
                isin=issuer.isin or None,
                lei=issuer.lei or None,
            )
            async with sem:
                try:
                    candidates = await cse_client.annual_reports(cse_iss, start_yr, end_yr)
                except Exception:
                    candidates = []

            # Group candidates by (fy, report_type)
            by_fy: dict[int, Any] = {}
            for cand in candidates:
                rtype = getattr(cand, "report_type", "AR")
                key = cand.fy
                if key and (key not in by_fy or cand.fy_confidence > by_fy[key].fy_confidence):
                    by_fy[key] = cand

            issuer_results = []
            for fy in cohort.fiscal_years:
                cand = by_fy.get(fy)
                rtype = getattr(cand, "report_type", "AR") if cand else "AR"
                slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}:{rtype}"
                if not cand:
                    issuer_results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="UNRESOLVED",
                        reason="No candidate filing found in CSE infoAnnualData",
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
                    continue

                temp_pdf = staging_dir / f"{issuer.ticker}_FY{fy}_{rtype}_temp.pdf"
                try:
                    download_meta = await downloader.get(cand.source_url, temp_pdf)
                    status, reason, final_path = promote_pdf_to_corpus(
                        source_pdf=temp_pdf,
                        output_root=output_corpus,
                        staging_root=self.staging_dir,
                        iso3="LKA",
                        mic="XCOL",
                        ticker=issuer.ticker,
                        fiscal_year=fy,
                        lei=issuer.lei,
                        isin=issuer.isin,
                        lang="EN",
                        report_type=rtype,
                    )
                    temp_pdf.unlink(missing_ok=True)
                    h, sz = compute_sha256_and_size(final_path) if final_path.exists() else ("", 0)
                    _, pages, _ = validate_pdf_bytes_or_file(final_path) if final_path.exists() else (False, 0, "")
                    issuer_results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status=status,
                        reason=reason,
                        sha256=h,
                        page_count=pages,
                        file_size_bytes=sz,
                        destination_path=str(final_path),
                        source_url=cand.source_url,
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
                except Exception as e:
                    temp_pdf.unlink(missing_ok=True)
                    issuer_results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="FAILED",
                        reason=f"Download/validation error: {str(e)}",
                        source_url=cand.source_url,
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
            return issuer_results

        try:
            batch_results = await asyncio.gather(*(process_issuer(iss) for iss in cohort.issuers))
            for res_list in batch_results:
                results.extend(res_list)
        finally:
            await cse_client.close()
            await downloader.close()

        return results


class AfricaAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("Africa")

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        from africa_ar_bulk.sources.universe import load_universe
        issuers = load_universe(local_dir=ROOT_DIR / "local")
        roster: List[CurrentIssuerRecord] = []
        now_str = datetime.now(timezone.utc).isoformat()
        for iss in issuers:
            roster.append(CurrentIssuerRecord(
                issuer_id=iss.issuer_id,
                legal_name=iss.company_name,
                country_iso3=iss.country_iso3,
                mic=iss.exchange_mic,
                ticker=iss.ticker,
                isin=iss.isin or "",
                lei=iss.lei or "",
                instrument_type="Equity",
                active_status="ACTIVE" if iss.active else "SUSPENDED",
                as_of_date=now_str,
                source_url=iss.source_url or "",
            ))
        return roster

    async def harvest_cohort(
        self,
        cohort: CohortManifest,
        output_corpus: Path,
    ) -> List[SlotResult]:
        from africa_ar_bulk.downloader import Downloader
        from africa_ar_bulk.models import Issuer as AfricaIssuer
        from africa_ar_bulk.sources.exchange_direct import DirectExchangeAdapter

        results: List[SlotResult] = []
        direct_adapter = DirectExchangeAdapter()
        downloader = Downloader(workers=8, rps=4.0)
        staging_dir = self.staging_dir
        staging_dir.mkdir(parents=True, exist_ok=True)

        async def process_issuer(issuer: CurrentIssuerRecord) -> List[SlotResult]:
            t0 = time.time()
            aff_iss = AfricaIssuer(
                issuer_id=issuer.issuer_id,
                country_iso3=issuer.country_iso3,
                exchange_mic=issuer.mic,
                ticker=issuer.ticker,
                company_name=issuer.legal_name,
                isin=issuer.isin,
                lei=issuer.lei,
            )
            min_fy = min(cohort.fiscal_years)
            max_fy = max(cohort.fiscal_years)
            try:
                candidates = await direct_adapter.discover_candidates(aff_iss, min_fy, max_fy)
            except Exception:
                candidates = []

            by_fy: dict[int, Any] = {}
            for cand in candidates:
                if cand.resolved_fy and (cand.resolved_fy not in by_fy or cand.fy_confidence > by_fy[cand.resolved_fy].fy_confidence):
                    by_fy[cand.resolved_fy] = cand

            issuer_results = []
            for fy in cohort.fiscal_years:
                cand = by_fy.get(fy)
                rtype = "AR"
                slot_id = f"{cohort.run_id}:{issuer.country_iso3}:{issuer.mic}:{issuer.ticker}:FY{fy}:{rtype}"
                if not cand or not cand.direct_pdf_url:
                    issuer_results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="UNRESOLVED",
                        reason=f"No candidate filing found for {issuer.country_iso3}:{issuer.ticker} FY{fy}",
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
                    continue

                temp_pdf = staging_dir / f"{issuer.country_iso3}_{issuer.ticker}_FY{fy}_{rtype}_temp.pdf"
                try:
                    _ = await downloader.get(cand.direct_pdf_url, temp_pdf)
                    status, reason, final_path = promote_pdf_to_corpus(
                        source_pdf=temp_pdf,
                        output_root=output_corpus,
                        staging_root=self.staging_dir,
                        iso3=issuer.country_iso3,
                        mic=issuer.mic,
                        ticker=issuer.ticker,
                        fiscal_year=fy,
                        lei=issuer.lei,
                        isin=issuer.isin,
                        lang="EN",
                        report_type=rtype,
                    )
                    temp_pdf.unlink(missing_ok=True)
                    h, sz = compute_sha256_and_size(final_path) if final_path.exists() else ("", 0)
                    _, pages, _ = validate_pdf_bytes_or_file(final_path) if final_path.exists() else (False, 0, "")
                    issuer_results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status=status,
                        reason=reason,
                        sha256=h,
                        page_count=pages,
                        file_size_bytes=sz,
                        destination_path=str(final_path),
                        source_url=cand.direct_pdf_url,
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
                except Exception as e:
                    temp_pdf.unlink(missing_ok=True)
                    issuer_results.append(SlotResult(
                        slot_id=slot_id,
                        run_id=cohort.run_id,
                        issuer_id=issuer.issuer_id,
                        fiscal_year=fy,
                        status="FAILED",
                        reason=f"Download/validation error: {str(e)}",
                        source_url=cand.direct_pdf_url,
                        elapsed_seconds=round(time.time() - t0, 2),
                    ))
            return issuer_results

        try:
            batch_results = await asyncio.gather(*(process_issuer(iss) for iss in cohort.issuers))
            for res_list in batch_results:
                results.extend(res_list)
        finally:
            await direct_adapter.close()
            await downloader.close()

        return results


def get_market_adapter(market_name: str) -> BaseMarketAdapter:
    norm = resolve_market_info(market_name)["name"]
    adapters = {
        "Australia": AustraliaAdapter,
        "India": IndiaAdapter,
        "HongKong": HongKongAdapter,
        "Singapore": SingaporeAdapter,
        "Canada": CanadaAdapter,
        "Bangladesh": BangladeshAdapter,
        "NewZealand": NewZealandAdapter,
        "SriLanka": SriLankaAdapter,
        "Africa": AfricaAdapter,
    }
    if norm not in adapters:
        raise ValueError(f"No adapter available for market '{market_name}'")
    return adapters[norm]()
