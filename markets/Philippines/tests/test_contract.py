import os
import pytest
from pathlib import Path

from phl_pse_bulk.contract import (
    allowed_pse_url,
    classify_attachment,
    extract_fiscal_year,
    is_annual_report_template,
)
from phl_pse_bulk.config import require_terms_ack


def test_exact_fy_extraction():
    text1 = "SEC FORM 17-A. For the fiscal year ended Dec 31, 2017"
    assert extract_fiscal_year(text1) == 2017

    text2 = "For the fiscal year ended December 31, 2024 of Ayala Corporation"
    assert extract_fiscal_year(text2) == 2024

    text3 = "period ended September 30, 2023"
    assert extract_fiscal_year(text3) == 2023


def test_template_filtering():
    assert is_annual_report_template("Annual Report", "17-1")
    assert is_annual_report_template("Annual Report", "")
    assert is_annual_report_template("", "17-A")
    assert not is_annual_report_template("Quarterly Report", "17-2")
    assert not is_annual_report_template("Current Report", "17-C")


def test_attachment_classification():
    assert classify_attachment("2024 SEC Form 17-A.pdf") == "AR_FULL"
    assert classify_attachment("AC_2023_Annual_Report.pdf") == "AR_FULL"
    assert classify_attachment("2024 Audited Financial Statements.pdf") == "AR_COMPONENT"
    assert classify_attachment("2024 Sustainability Report.pdf") == "SR"
    assert classify_attachment("2023 ESG Progress Report.pdf") == "SR"
    assert classify_attachment("17-Q Third Quarter Report.pdf") == "OTHER"


def test_ssrf_boundary_guard():
    assert allowed_pse_url("/downloadFile.do?file_id=12345").startswith("https://edge.pse.com.ph/")
    assert allowed_pse_url("https://edge.pse.com.ph/downloadHtml.do?file_id=99").startswith("https://edge.pse.com.ph/")

    with pytest.raises(ValueError):
        allowed_pse_url("https://external-malicious-site.com/file.pdf")

    with pytest.raises(ValueError):
        allowed_pse_url("http://edge.pse.com.ph/downloadFile.do")


def test_terms_gate(monkeypatch):
    monkeypatch.delenv("PSE_TERMS_ACKNOWLEDGED", raising=False)
    with pytest.raises(RuntimeError):
        require_terms_ack()

    monkeypatch.setenv("PSE_TERMS_ACKNOWLEDGED", "1")
    require_terms_ack()
