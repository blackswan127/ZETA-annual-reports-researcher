from __future__ import annotations

import asyncio
import os
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

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from asx_bulk.source import ASXSource
        source = ASXSource(timeout=30.0, retries=3, metadata_rps=3.0)
        try:
            records = await source.current_issuers()
        finally:
            await source.close()

        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        roster = []
        for r in records:
            ticker = r.ticker.strip().upper()
            roster.append(CurrentIssuerRecord(
                issuer_id=ticker,
                legal_name=r.name,
                country_iso3="AUS",
                mic="XASX",
                ticker=ticker,
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
                slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}"
                # Search downloaded PDF in work_dir
                matched_pdf = None
                company_pattern = f"{issuer.ticker}_*"
                fy_dir = work_dir / "pdfs"
                if fy_dir.exists():
                    for f in fy_dir.glob(f"{company_pattern}/{fy}/*.pdf"):
                        matched_pdf = f
                        break
                    if not matched_pdf:
                        for f in fy_dir.glob(f"{issuer.ticker}*/**/{fy}/*.pdf"):
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


class IndiaAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("India")

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from india_ar_bulk.source import NSESource, BSESource, current_india_universe
        os.environ["INDIA_AR_ACKNOWLEDGE_TERMS"] = "1"
        n = NSESource(timeout=30.0, retries=3, rps=1.5)
        b = BSESource(timeout=30.0, retries=3, rps=2.5)
        try:
            issuers, stats = await current_india_universe(n, b, include_sme=True)
        finally:
            await n.close()
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
                mic="XNSE" if i.nse_symbol else "XBOM",
                ticker=i.nse_symbol or i.bse_scrip,
                isin=i.isin,
                instrument_type="Equity",
                active_status="ACTIVE",
                as_of_date=as_of,
                secondary_mic="XBOM" if (i.nse_symbol and i.bse_scrip) else "",
                secondary_ticker=i.bse_scrip if i.nse_symbol else "",
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
            work_dir, start_yr, end_yr,
            metadata_workers=6, nse_rps=1.5, bse_rps=2.5,
            download_workers=8, download_rps=4.0, timeout=45.0, retries=5,
            chunk_size=1024*1024, include_sme=True, use_bse_fallback=True, deep_bse_fallback=False
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
        for issuer in cohort.issuers:
            for fy in cohort.fiscal_years:
                slot_id = f"{cohort.run_id}:{issuer.ticker}:FY{fy}"
                matched_pdf = None
                fy_dir = work_dir / "pdfs"
                if fy_dir.exists():
                    for f in fy_dir.glob(f"*{issuer.ticker}*/**/{fy}/*.pdf"):
                        matched_pdf = f
                        break
                    if not matched_pdf:
                        for f in fy_dir.glob(f"*{issuer.issuer_id}*/**/{fy}/*.pdf"):
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


class CanadaAdapter(BaseMarketAdapter):
    def __init__(self):
        super().__init__("Canada")

    async def load_roster(self, refresh: bool = False) -> List[CurrentIssuerRecord]:
        ensure_sys_paths()
        from canada_zeta_bulk.universe import fetch_latest_tmx_list, parse_universe_file
        # Check if local tmx file exists
        example_csv = ROOT_DIR / "markets" / "Canada" / "input" / "tmx_current_list.example.csv"
        if example_csv.exists():
            issuers = parse_universe_file(example_csv, include_nex=False)
        else:
            try:
                issuers, _ = await fetch_latest_tmx_list(30.0, include_nex=False)
            except Exception:
                issuers = []

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
    }
    if norm not in adapters:
        raise ValueError(f"No adapter available for market '{market_name}'")
    return adapters[norm]()
