from datetime import date
from asx_bulk.classifier import annual_score, infer_fiscal_year

def test_annual_score_accepts_realistic_titles():
    assert annual_score("FY25 Annual Report and Financial Statements", 137) > 90
    assert annual_score("Appendix 4E and Annual Report for Year Ended 30 June 2024", 57) > 90
    assert annual_score("Annual Report to Shareholders", 170) > 80

def test_annual_score_rejects_false_positives():
    assert annual_score("Release and dispatch of 2025 Annual Report", 1) < 0
    assert annual_score("FY25 Annual Report Supplementary Information", 5) < 0
    assert annual_score("Notice of Annual General Meeting/Proxy Form", 30) < 0
    assert annual_score("Half-year report and Appendix 4D", 55) < 0

def test_infer_explicit_and_heuristic_year():
    assert infer_fiscal_year("FY25 Annual Report", date(2025, 9, 1)) == (2025, "title_fy2")
    assert infer_fiscal_year("2024 Annual Report", date(2025, 3, 1))[0] == 2024
    assert infer_fiscal_year("Annual Report for year ended 31 December 2024 - lodged 2025", date(2025, 3, 1))[0] == 2024
    assert infer_fiscal_year("Annual Report", date(2026, 3, 1))[0] == 2025
    assert infer_fiscal_year("Annual Report", date(2025, 9, 1))[0] == 2025
