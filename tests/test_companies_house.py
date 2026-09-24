"""Offline unit tests for Companies House matching, accounts discovery, and rate budgeting."""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from annual_reports.catalog import Report
from annual_reports.companies_house import (
    CH_API_HOSTS,
    CH_DOC_API_BASE,
    CH_WEB_BASE,
    CompaniesHouseClient,
    PersistedRollingRateGate,
    classify_ch_accounts_filing,
    ensure_ch_schema,
    evaluate_company_match,
    export_ch_manifest,
    export_ch_review,
    normalize_company_name,
    normalize_uk_crn,
    parse_period_end_date,
)
from annual_reports.discovery import Company, DiscoveryStore


def test_normalize_company_name():
    assert normalize_company_name("BP P.L.C.") == "BP"
    assert normalize_company_name("THE BRITISH PETROLEUM COMPANY P.L.C.") == "BRITISH PETROLEUM COMPANY"
    assert normalize_company_name("BARCLAYS PLC /NEW/") == "BARCLAYS"
    assert normalize_company_name("ASTRAZENECA (UK) LIMITED") == "ASTRAZENECA"


def test_normalize_uk_crn():
    assert normalize_uk_crn("102498") == "00102498"
    assert normalize_uk_crn("00102498") == "00102498"
    assert normalize_uk_crn("sc095000") == "SC095000"
    assert normalize_uk_crn(" NI123456 ") == "NI123456"
    assert normalize_uk_crn("") == ""


def test_parse_period_end_date():
    date_str, fy = parse_period_end_date("made up to 31 December 2024")
    assert date_str == "2024-12-31"
    assert fy == 2024

    date_str2, fy2 = parse_period_end_date("made up to 5 April 2023")
    assert date_str2 == "2023-04-05"
    assert fy2 == 2023

    date_str3, fy3 = parse_period_end_date("2022-06-30")
    assert date_str3 == "2022-06-30"
    assert fy3 == 2022


def test_classify_accounts_strict_rules():
    # Eligible full group accounts
    status, reason = classify_ch_accounts_filing(
        form_type="AA",
        description="Group of companies' accounts made up to 31 December 2024",
        period_end="2024-12-31",
        has_pdf=True,
        pages=280,
    )
    assert status == "AR"
    assert reason == ""

    # Dormant accounts -> EXCLUDED
    status, reason = classify_ch_accounts_filing(
        form_type="AA",
        description="Dormant company accounts made up to 31 December 2024",
        period_end="2024-12-31",
        has_pdf=True,
    )
    assert status == "EXCLUDED"
    assert "dormant" in reason

    # Micro-entity accounts -> EXCLUDED
    status, reason = classify_ch_accounts_filing(
        form_type="AA",
        description="Micro-entity accounts made up to 31 December 2024",
        period_end="2024-12-31",
        has_pdf=True,
    )
    assert status == "EXCLUDED"
    assert "micro_entity" in reason

    # Abbreviated/small filleted accounts -> EXCLUDED
    status, reason = classify_ch_accounts_filing(
        form_type="AA",
        description="Total exemption small company accounts made up to 31 December 2024",
        period_end="2024-12-31",
        has_pdf=True,
    )
    assert status == "EXCLUDED"

    # Non-accounts form (AA01 - change of accounting date) -> EXCLUDED
    status, reason = classify_ch_accounts_filing(
        form_type="AA01",
        description="Change of accounting reference date",
        period_end="2024-12-31",
        has_pdf=True,
    )
    assert status == "EXCLUDED"
    assert "non_accounts_form" in reason

    # Amended accounts -> REVIEW
    status, reason = classify_ch_accounts_filing(
        form_type="AAMD",
        description="Amended group accounts made up to 31 December 2024",
        period_end="2024-12-31",
        has_pdf=True,
    )
    assert status == "REVIEW"
    assert "amended" in reason

    # Suspiciously short page count (< 8 pages) -> REVIEW
    status, reason = classify_ch_accounts_filing(
        form_type="AA",
        description="Group of companies' accounts made up to 31 December 2024",
        period_end="2024-12-31",
        has_pdf=True,
        pages=4,
    )
    assert status == "REVIEW"
    assert "short_page_count" in reason

    # PDF unavailable -> EXCLUDED
    status, reason = classify_ch_accounts_filing(
        form_type="AA",
        description="Full accounts made up to 31 December 2024",
        period_end="2024-12-31",
        has_pdf=False,
    )
    assert status == "EXCLUDED"
    assert reason == "pdf_unavailable"


def test_evaluate_company_match():
    plc = Company("GBR", "Barclays PLC", "XLON", "213800LBQA1Y9L22JB70", "GB0031348658", "BARC", "")

    # Exact match confirmed by GLEIF CRN and PLC type
    gleif_info = {
        "legal_name": "BARCLAYS PLC",
        "registered_as": "01026167",
        "jurisdiction": "GB-ENG",
    }
    ch_profile = {
        "company_number": "01026167",
        "company_name": "BARCLAYS PLC",
        "type": "plc",
        "company_status": "active",
        "previous_company_names": [],
    }
    status, crn, ev = evaluate_company_match(plc, gleif_info, ch_profile)
    assert status == "VERIFIED"
    assert crn == "01026167"

    # Listed PLC accidentally matched to a private Limited subsidiary without GLEIF CRN confirmation -> REVIEW
    ch_sub_profile = {
        "company_number": "09999999",
        "company_name": "BARCLAYS SERVICES LIMITED",
        "type": "ltd",
        "company_status": "active",
    }
    status_sub, _, ev_sub = evaluate_company_match(plc, None, ch_sub_profile)
    assert status_sub == "REVIEW"
    assert "subsidiary" in ev_sub.get("reason", "")

    # Non-UK incorporated offshore entity (Jersey JE prefix) with no UK CRN -> UNAVAILABLE
    jersey_co = Company("GBR", "Glencore PLC", "XLON", "2138002658TEGI15HZ10", "JE00B4T3BW64", "GLEN", "")
    gleif_jersey = {"registered_as": "107658", "jurisdiction": "JE"}
    status_je, _, ev_je = evaluate_company_match(jersey_co, gleif_jersey, None)
    assert status_je == "UNAVAILABLE"


def test_persisted_rolling_rate_gate(tmp_path: Path):
    state_file = tmp_path / "test_rate.sqlite3"
    gate = PersistedRollingRateGate(
        state_path=state_file,
        max_requests=3,
        window_s=1.0,
        min_interval_s=0.05,
    )

    async def run_burst():
        # First 3 should proceed quickly
        t0 = asyncio.get_event_loop().time()
        for _ in range(3):
            await gate.wait()
        t1 = asyncio.get_event_loop().time()
        assert t1 - t0 < 0.5

        # 4th request must wait for sliding window (window_s = 1.0)
        await gate.wait()
        t2 = asyncio.get_event_loop().time()
        assert t2 - t0 >= 0.9

    asyncio.run(run_burst())


def test_export_ch_manifest_and_review(tmp_path: Path):
    state_file = tmp_path / "state.sqlite3"
    from annual_reports.engine import StateStore
    state_store = StateStore(state_file)
    store = DiscoveryStore(state_file)
    ensure_ch_schema(store.connection)

    co = Company("GBR", "Test Co PLC", "XLON", "213800TEST1234567890", "GB00TEST1234", "TEST", "")
    store.add_universe([co], [2022, 2023, 2024])

    # Mark 2022 as already downloaded in reports
    prior_rep = Report.from_row({
        "country": "GBR", "exchange": "XLON", "lei": co.lei, "isin": co.isin,
        "ticker": co.ticker, "fiscal_year": "FY2022", "report_type": "AR",
        "language": "EN", "pdf_url": "https://data.fca.org.uk/artefacts/test.pdf",
        "source_page": "", "verified": "true",
    })
    store.connection.execute(
        "INSERT INTO reports VALUES (?,?,?,?, 'downloaded', 1000, 50, 'abc', 1.0, '', '2026-01-01')",
        (str(prior_rep.relative_path), prior_rep.pdf_url, "", 1),
    )

    # Insert verified match
    store.connection.execute(
        "INSERT INTO company_house_matches VALUES (?, ?, ?, 'VERIFIED', '2026-01-01')",
        (co.key, "00123456", json.dumps({"reason": "test"})),
    )

    # Insert candidate for 2022 (should be skipped because 2022 is already verified)
    store.upsert_candidate(
        company_key=co.key, report_year=2022, source="COMPANIES_HOUSE",
        source_record_id="00123456:tx2022",
        source_url=f"{CH_WEB_BASE}/company/00123456/filing-history/tx2022/document?format=pdf",
        source_format="PDF", form_type="AA", status="VERIFIED_DIRECT_PDF", verified=True,
    )
    # Insert candidate for 2023 (missing slot -> should be exported!)
    store.upsert_candidate(
        company_key=co.key, report_year=2023, source="COMPANIES_HOUSE",
        source_record_id="00123456:tx2023",
        source_url=f"{CH_WEB_BASE}/company/00123456/filing-history/tx2023/document?format=pdf",
        source_format="PDF", form_type="AA", status="VERIFIED_DIRECT_PDF", verified=True,
    )
    # Insert candidate for 2024 marked REVIEW
    store.upsert_candidate(
        company_key=co.key, report_year=2024, source="COMPANIES_HOUSE",
        source_record_id="00123456:tx2024",
        source_url=f"{CH_WEB_BASE}/company/00123456/filing-history/tx2024/document?format=pdf",
        source_format="PDF", form_type="AA", status="REVIEW", verified=False,
    )
    store.connection.commit()
    store.close()
    state_store.close()

    manifest_csv = tmp_path / "ch_manifest.csv"
    count = export_ch_manifest(state_file, manifest_csv, years=[2022, 2023, 2024])
    # Only FY2023 should be exported (FY2022 was skipped, FY2024 is in REVIEW)
    assert count == 1
    content = manifest_csv.read_text(encoding="utf-8")
    assert "FY2023" in content
    assert "FY2022" not in content
    assert "FY2024" not in content

    # Export review CSV
    review_csv = tmp_path / "ch_review.csv"
    rev_summary = export_ch_review(state_file, review_csv)
    assert rev_summary["rows_written"] >= 0
