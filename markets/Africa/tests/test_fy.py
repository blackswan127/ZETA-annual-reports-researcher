import pytest
from africa_ar_bulk.fy import resolve_fy


def test_resolve_fy_explicit_tokens():
    fy, conf, method = resolve_fy("Annual Report FY2024")
    assert fy == 2024
    assert conf >= 0.95

    fy, conf, method = resolve_fy("Integrated Report FY23")
    assert fy == 2023
    assert conf >= 0.90


def test_resolve_fy_year_ranges():
    fy, conf, method = resolve_fy("Annual Report 2023/24")
    assert fy == 2024
    assert conf >= 0.90

    fy, conf, method = resolve_fy("Audited Accounts 2022-2023")
    assert fy == 2023
    assert conf >= 0.90


def test_resolve_fy_period_ended():
    fy, conf, method = resolve_fy("Annual Report for the year ended 31 December 2022")
    assert fy == 2022
    assert conf >= 0.98

    fy, conf, method = resolve_fy("Integrated Report for the period ended 30 June 2024")
    assert fy == 2024
    assert conf >= 0.98


def test_resolve_fy_metadata_period():
    fy, conf, method = resolve_fy("Annual Report", metadata_period="2023-12-31")
    assert fy == 2023
    assert conf == 1.0


def test_resolve_fy_title_years():
    fy, conf, method = resolve_fy("Annual Report 2021")
    assert fy == 2021
    assert conf >= 0.85

    fy, conf, method = resolve_fy("2020 Integrated Annual Report")
    assert fy == 2020
    assert conf >= 0.85
