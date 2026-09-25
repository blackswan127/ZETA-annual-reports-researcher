from india_ar_bulk.classify import annual_report_score,is_annual_report,fiscal_year_from_text

def test_classifier():
    assert is_annual_report('Annual Report 2024-25')
    assert is_annual_report('Reg. 34 (1) - Annual Report')
    assert not is_annual_report('Annual Return for FY 2024-25')
    assert not is_annual_report('Business Responsibility and Sustainability Report')

def test_fiscal_year():
    assert fiscal_year_from_text('Annual Report 2024-25')==2025
    assert fiscal_year_from_text('FY2023')==2023
    assert fiscal_year_from_text('year ended March 31, 2022')==2022
