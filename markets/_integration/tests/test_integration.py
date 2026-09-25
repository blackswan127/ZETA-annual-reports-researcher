import pytest
from pathlib import Path
from pypdf import PdfWriter

from markets._integration.contract import (
    CurrentIssuerRecord,
    resolve_market_info,
)
from markets._integration.promotion import (
    build_sop_relative_path,
    is_valid_isin,
    is_valid_lei,
    promote_pdf_to_corpus,
    validate_pdf_bytes_or_file,
)
from markets._integration.cohort import (
    deduplicate_india_roster,
    select_exact_cohort,
)
from markets._integration.coordinator import parse_plain_english_directive


def create_dummy_pdf(path: Path, pages: int = 2) -> None:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=300, height=300)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        w.write(f)


def test_market_resolution():
    cases = [
        ("Australia", "AUS", "XASX"),
        ("ASX", "AUS", "XASX"),
        ("Bangladesh", "BGD", "XDHA"),
        ("DSE", "BGD", "XDHA"),
        ("Canada", "CAN", "XTSE"),
        ("TSX", "CAN", "XTSE"),
        ("HongKong", "HKG", "XHKG"),
        ("HKEX", "HKG", "XHKG"),
        ("India", "IND", "XNSE"),
        ("BSE", "IND", "XNSE"),
        ("NSE", "IND", "XNSE"),
        ("NewZealand", "NZL", "XNZE"),
        ("NZX", "NZL", "XNZE"),
        ("Singapore", "SGP", "XSES"),
        ("SGX", "SGP", "XSES"),
        ("SriLanka", "LKA", "XCOL"),
        ("CSE", "LKA", "XCOL"),
        ("COLOMBO", "LKA", "XCOL"),
        ("Africa", "ZAF", "XJSE"),
        ("SouthAfrica", "ZAF", "XJSE"),
        ("Nigeria", "ZAF", "XJSE"),
        ("Kenya", "ZAF", "XJSE"),
        ("MiddleEast", "OMN", "XMUS"),
        ("Oman", "OMN", "XMUS"),
        ("Jordan", "OMN", "XMUS"),
        ("SaudiArabia", "OMN", "XMUS"),
        ("DFM", "OMN", "XMUS"),
    ]
    for raw, exp_iso3, exp_mic in cases:
        info = resolve_market_info(raw)
        assert info["iso3"] == exp_iso3
        assert info["mic"] == exp_mic


def test_sop_relative_path():
    lei = "5493001KJTIIGC8Y1R12"
    isin = "AU000000BHP4"
    ticker = "BHP"
    fy = 2024
    rel = build_sop_relative_path("AUS", "XASX", lei, isin, ticker, fy, "EN")
    expected = Path("AUS/XASX/5493001KJTIIGC8Y1R12_AU000000BHP4_BHP/FY2024/5493001KJTIIGC8Y1R12_AUS_XASX_BHP_AU000000BHP4_FY2024_AR_EN.pdf")
    assert rel.as_posix() == expected.as_posix()


def test_pdf_validation(tmp_path):
    pdf = tmp_path / "valid.pdf"
    create_dummy_pdf(pdf, pages=3)
    ok, pages, reason = validate_pdf_bytes_or_file(pdf)
    assert ok is True
    assert pages == 3
    assert reason == "OK"

    bad = tmp_path / "corrupt.pdf"
    bad.write_text("NOT A PDF FILE")
    ok_bad, pages_bad, _ = validate_pdf_bytes_or_file(bad)
    assert ok_bad is False
    assert pages_bad == 0


def test_promote_pdf_to_corpus_complete_identity(tmp_path):
    src = tmp_path / "source.pdf"
    create_dummy_pdf(src, pages=2)
    corpus = tmp_path / "GLOBAL_SUSTAINABILITY_DATABASE"
    staging = tmp_path / "staging"
    lei = "5493001KJTIIGC8Y1R12"
    isin = "AU000000BHP4"

    status, reason, dest = promote_pdf_to_corpus(
        source_pdf=src,
        output_root=corpus,
        staging_root=staging,
        iso3="AUS",
        mic="XASX",
        ticker="BHP",
        fiscal_year=2024,
        lei=lei,
        isin=isin,
    )
    assert status == "PROMOTED"
    assert dest.exists()
    assert "AUS/XASX" in dest.as_posix()
    assert dest.name == f"{lei}_AUS_XASX_BHP_{isin}_FY2024_AR_EN.pdf"

    # Test idempotence on identical file
    status2, _, dest2 = promote_pdf_to_corpus(
        source_pdf=src,
        output_root=corpus,
        staging_root=staging,
        iso3="AUS",
        mic="XASX",
        ticker="BHP",
        fiscal_year=2024,
        lei=lei,
        isin=isin,
    )
    assert status2 == "IDEMPOTENT_EXISTING"


def test_promote_pdf_to_corpus_missing_identity(tmp_path):
    src = tmp_path / "source.pdf"
    create_dummy_pdf(src, pages=1)
    corpus = tmp_path / "GLOBAL_SUSTAINABILITY_DATABASE"
    staging = tmp_path / "staging"

    # Missing LEI and ISIN: must route to staging
    status, reason, dest = promote_pdf_to_corpus(
        source_pdf=src,
        output_root=corpus,
        staging_root=staging,
        iso3="AUS",
        mic="XASX",
        ticker="BHP",
        fiscal_year=2024,
        lei="",
        isin="",
    )
    assert status == "STAGED_UNRESOLVED_IDENTITY"
    assert "LEI invalid or missing" in reason
    assert dest.exists()
    assert staging in dest.parents
    assert corpus not in dest.parents


def test_promote_pdf_to_corpus_conflict(tmp_path):
    src1 = tmp_path / "report1.pdf"
    create_dummy_pdf(src1, pages=2)
    corpus = tmp_path / "GLOBAL_SUSTAINABILITY_DATABASE"
    staging = tmp_path / "staging"
    lei = "5493001KJTIIGC8Y1R12"
    isin = "AU000000BHP4"

    # First promotion
    promote_pdf_to_corpus(src1, corpus, staging, "AUS", "XASX", "BHP", 2024, lei, isin)

    # Different report content
    src2 = tmp_path / "report2.pdf"
    create_dummy_pdf(src2, pages=5)

    status, reason, conflict_path = promote_pdf_to_corpus(
        src2, corpus, staging, "AUS", "XASX", "BHP", 2024, lei, isin
    )
    assert status == "CONFLICT"
    assert "conflicts" in conflict_path.as_posix()
    assert conflict_path.exists()


def test_india_deduplication():
    records = [
        CurrentIssuerRecord(issuer_id="NSE_RELIANCE", legal_name="Reliance Industries", country_iso3="IND", mic="XNSE", ticker="RELIANCE", isin="INE002A01018"),
        CurrentIssuerRecord(issuer_id="BSE_500325", legal_name="Reliance Industries Ltd", country_iso3="IND", mic="XBOM", ticker="500325", isin="INE002A01018"),
        CurrentIssuerRecord(issuer_id="NSE_TCS", legal_name="Tata Consultancy Services", country_iso3="IND", mic="XNSE", ticker="TCS", isin="INE467B01029"),
    ]
    deduped = deduplicate_india_roster(records)
    assert len(deduped) == 2
    rel = next(r for r in deduped if r.isin == "INE002A01018")
    assert rel.ticker == "RELIANCE"
    assert rel.mic == "XNSE"
    assert rel.secondary_mic == "XBOM"
    assert rel.secondary_ticker == "500325"


def test_exact_n_cohort_selection(tmp_path):
    roster = [
        CurrentIssuerRecord(issuer_id=f"T{i}", legal_name=f"Company {i}", country_iso3="AUS", mic="XASX", ticker=f"T{i}", isin=f"AU00000000{i:02d}", lei=f"5493001KJTIIGC8Y1R{i:02d}")
        for i in range(20)
    ]
    manifest = select_exact_cohort(
        market="Australia",
        requested_count=5,
        fiscal_years=[2024],
        roster=roster,
        corpus_root=tmp_path / "corpus",
        manifest_dir=tmp_path / "manifests",
        offset=0,
    )
    assert len(manifest.issuers) == 5
    assert [i.ticker for i in manifest.issuers] == ["T0", "T1", "T10", "T11", "T12"]
    assert (tmp_path / "manifests" / f"{manifest.run_id}.json").exists()
    assert (tmp_path / "manifests" / f"{manifest.run_id}.csv").exists()


def test_plain_english_directive_parsing():
    res1 = parse_plain_english_directive("download the next 100 current listed companies in India for FY2024")
    assert res1["market"] == "India"
    assert res1["count"] == 100
    assert res1["fiscal_years"] == [2024]
    assert res1["offset"] == -1

    res2 = parse_plain_english_directive("harvest 25 companies from ASX for FY2020-FY2024")
    assert res2["market"] == "Australia"
    assert res2["count"] == 25
    assert res2["fiscal_years"] == [2020, 2021, 2022, 2023, 2024]

    res3 = parse_plain_english_directive("run SGX 50 issuers 2023")
    assert res3["market"] == "Singapore"
    assert res3["count"] == 50
    assert res3["fiscal_years"] == [2023]


def test_get_market_adapter_srilanka():
    from markets._integration.adapters import get_market_adapter, SriLankaAdapter
    adapter = get_market_adapter("SriLanka")
    assert isinstance(adapter, SriLankaAdapter)
    adapter_cse = get_market_adapter("CSE")
    assert isinstance(adapter_cse, SriLankaAdapter)
    assert adapter.info["iso3"] == "LKA"
    assert adapter.info["mic"] == "XCOL"


def test_get_market_adapter_africa():
    from markets._integration.adapters import get_market_adapter, AfricaAdapter
    adapter = get_market_adapter("Africa")
    assert isinstance(adapter, AfricaAdapter)
    adapter_jse = get_market_adapter("SouthAfrica")
    assert isinstance(adapter_jse, AfricaAdapter)
    adapter_ngx = get_market_adapter("Nigeria")
    assert isinstance(adapter_ngx, AfricaAdapter)

    # Test directive parsing
    res = parse_plain_english_directive("harvest 20 companies from Nigeria for FY2023")
    assert res["market"] == "Africa"
    assert res["count"] == 20
    assert res["fiscal_years"] == [2023]


def test_get_market_adapter_middle_east():
    from markets._integration.adapters import get_market_adapter, MiddleEastAdapter
    adapter = get_market_adapter("MiddleEast")
    assert isinstance(adapter, MiddleEastAdapter)
    adapter_oman = get_market_adapter("Oman")
    assert isinstance(adapter_oman, MiddleEastAdapter)
    adapter_saudi = get_market_adapter("SaudiArabia")
    assert isinstance(adapter_saudi, MiddleEastAdapter)
    adapter_dfm = get_market_adapter("DFM")
    assert isinstance(adapter_dfm, MiddleEastAdapter)

    # Test directive parsing
    res = parse_plain_english_directive("harvest 25 companies from Oman for FY2023")
    assert res["market"] == "MiddleEast"
    assert res["count"] == 25
    assert res["fiscal_years"] == [2023]

    res2 = parse_plain_english_directive("download 10 issuers in Saudi Arabia for FY2024")
    assert res2["market"] == "MiddleEast"
    assert res2["count"] == 10
    assert res2["fiscal_years"] == [2024]


def test_middle_east_exclusions():
    # User directive: ignore palestine & israel
    with pytest.raises(ValueError, match="excluded"):
        resolve_market_info("Palestine")

    with pytest.raises(ValueError, match="excluded"):
        resolve_market_info("Israel")

    with pytest.raises(ValueError, match="excluded"):
        parse_plain_english_directive("harvest 10 companies from Palestine for FY2024")

    with pytest.raises(ValueError, match="excluded"):
        parse_plain_english_directive("download issuers in Israel")

