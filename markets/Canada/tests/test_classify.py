from canada_zeta_bulk.classify import classify_title, infer_fiscal_year, detect_language

def test_annual_report_classifier():
    ok,score=classify_title("2024 Annual Report","x.pdf")
    assert ok and score>=80
    assert classify_title("2024 Annual Information Form","aif.pdf")[0] is False
    assert classify_title("2024 Sustainability Report","s.pdf")[0] is False

def test_fiscal_year_period_end_wins():
    assert infer_fiscal_year("Annual Report","2024-12-31","2025-03-01","")[0]==2024

def test_fiscal_year_title():
    assert infer_fiscal_year("Annual Report 2023","","","")== (2023,"title")

def test_language():
    assert detect_language("Rapport annuel 2024","report_fr.pdf","")=="FR"
    assert detect_language("Annual Report 2024","report.pdf","")=="EN"
