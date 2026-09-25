import pytest
from africa_ar_bulk.classify import classify_document


def test_positive_annual_reports():
    positives = [
        "Annual Report and Financial Statements 2024",
        "Integrated Annual Report 2023",
        "Annual Integrated Report for the year ended 31 December 2022",
        "Annual Report & Accounts 2021",
        "Annual Report to Shareholders 2020",
        "Audited Annual Financial Statements 2019",
        "Integrated Report 2024",
    ]
    for title in positives:
        is_ar, label, score = classify_document(title)
        assert is_ar is True, f"Failed positive match: {title}"
        assert label == "AR"
        assert score >= 50.0


def test_negative_exclusions():
    negatives = [
        "Interim Financial Results for the six months ended 30 June 2024",
        "Half-year financial report 2023",
        "Quarterly Report Q1 2024",
        "Notice of Annual General Meeting and Proxy Form",
        "Notice of AGM 2023",
        "Abridged Audited Financial Results 2022",
        "Press Release - Annual Results 2021",
        "Dividend Announcement FY2023",
        "Corporate Governance Report 2024",
        "Investor Presentation FY2023",
    ]
    for title in negatives:
        is_ar, label, score = classify_document(title)
        assert is_ar is False, f"Failed negative exclusion: {title}"
        assert label == "OTHER"
        assert score < 50.0


def test_sustainability_and_esg_classification():
    sustainability_samples = [
        "Sustainability Report 2023",
        "ESG Report and Climate Disclosures 2022",
        "Corporate Social Responsibility Report 2021",
        "Sustainability Review 2020",
        "Annual Sustainability and Governance Report 2024",
    ]
    for title in sustainability_samples:
        is_valid, label, score = classify_document(title)
        assert is_valid is True, f"Failed sustainability match: {title}"
        assert label == "SR"
        assert score >= 50.0
