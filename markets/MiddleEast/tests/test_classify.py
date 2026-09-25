from __future__ import annotations

import pytest

from me_ar_bulk.classify import classify_document, detect_language


def test_classify_full_annual_reports():
    cases = [
        ("Bank Muscat Annual Report 2023", "AR_FULL"),
        ("Emaar Properties Integrated Annual Report 2022", "AR_FULL"),
        ("Saudi Aramco Annual Report and Financial Statements 2023", "AR_FULL"),
        ("Annual Financial Report 2021", "AR_FULL"), # ASE Jordan category
        ("Bank Dhofar AR EN 2024", "AR_FULL"),       # MSX Oman explicit
    ]
    for title, expected in cases:
        doc_class, conf = classify_document(title)
        assert doc_class == expected, f"Failed for '{title}' -> got {doc_class}"
        assert conf >= 0.80


def test_classify_statements_only_components():
    cases = [
        ("Audited Financial Statements for the year ended 31 December 2023", "ANNUAL_FS_COMPONENT"),
        ("Independent Auditor's Report and Financial Statements 2022", "ANNUAL_FS_COMPONENT"),
        ("Annual Financial Statements 2024", "ANNUAL_FS_COMPONENT"),
    ]
    for title, expected in cases:
        doc_class, conf = classify_document(title)
        assert doc_class == expected, f"Failed for '{title}' -> got {doc_class}"
        assert conf >= 0.85


def test_classify_rejections():
    cases = [
        ("Q1 2024 Financial Results", "REJECT"),
        ("Half-Year Report for June 2023", "REJECT"),
        ("Notice of Annual General Meeting and Proxy Form", "REJECT"),
        ("Board Meeting Minutes and Dividend Recommendation", "REJECT"),
        ("Press Release - FY2023 Earnings Highlights", "REJECT"),
    ]
    for title, expected in cases:
        doc_class, _ = classify_document(title)
        assert doc_class == expected, f"Failed for '{title}' -> got {doc_class}"


def test_classify_governance_and_esg():
    g_class, _ = classify_document("Corporate Governance Report 2023")
    assert g_class == "GOVERNANCE_COMPONENT"

    e_class, _ = classify_document("Sustainability Report 2023")
    assert e_class == "ESG_COMPONENT"


def test_detect_language():
    # Explicit EN
    lang, conf = detect_language("Bank Muscat Annual Report AR EN", filename="report_en.pdf")
    assert lang == "EN"
    assert conf >= 0.90

    # Arabic text
    arabic_sample = "تقرير سنوي والبيانات المالية المدققة لمصرف الراجحي لعام 2023"
    lang_ar, conf_ar = detect_language(arabic_sample)
    assert lang_ar == "AR"
    assert conf_ar >= 0.90
