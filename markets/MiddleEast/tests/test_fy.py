from __future__ import annotations

import pytest

from me_ar_bulk.fy import resolve_fiscal_year


def test_resolve_fy_explicit_period_end():
    # ISO date
    fy, conf, method = resolve_fiscal_year(period_end="2023-12-31")
    assert fy == 2023
    assert conf == 0.99
    assert "ISO" in method

    # DMY date
    fy, conf, method = resolve_fiscal_year(period_end="31/12/2024")
    assert fy == 2024
    assert conf == 0.99
    assert "DMY" in method

    # Text date
    fy, conf, method = resolve_fiscal_year(period_end="31 December 2022")
    assert fy == 2022
    assert conf == 0.99
    assert "TEXT" in method


def test_resolve_fy_tokens():
    fy, conf, method = resolve_fiscal_year(title="Annual Report FY2023")
    assert fy == 2023
    assert conf >= 0.90
    assert "FY_TOKEN" in method

    fy2, conf2, method2 = resolve_fiscal_year(title="Annual Report FY24")
    assert fy2 == 2024
    assert conf2 >= 0.90


def test_resolve_fy_ranges():
    fy, conf, method = resolve_fiscal_year(title="Integrated Report 2023/2024")
    assert fy == 2024
    assert conf >= 0.90

    fy_short, conf_short, _ = resolve_fiscal_year(title="Annual Report 2022-23")
    assert fy_short == 2023
    assert conf_short >= 0.90


def test_resolve_fy_standalone_year():
    fy, conf, method = resolve_fiscal_year(title="Arab Bank Annual Report 2021")
    assert fy == 2021
    assert conf == 0.85
    assert method == "TITLE_STANDALONE_YEAR"


def test_resolve_fy_unresolved():
    fy, conf, method = resolve_fiscal_year(title="General Disclosure Document")
    assert fy is None
    assert conf == 0.0
    assert method == "UNRESOLVED"
