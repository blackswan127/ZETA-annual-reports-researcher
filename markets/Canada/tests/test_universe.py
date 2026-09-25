from canada_zeta_bulk.universe import parse_csv_bytes, normalize_exchange, eligible_company

def test_parse_current_tmx_csv_filters_products():
    data=b"Company Name,Symbol,Exchange,Security Type,Industry,Website,ISIN,LEI\nRoyal Bank of Canada,RY,TSX,Common Shares,Banks,https://rbc.com,CA7800871021,ES7IP3U3RHIGC71XBU11\nExample ETF,ETF1,TSX,ETF,Exchange Traded Fund,,,\nJunior Mine,JMN,TSX Venture,Common Shares,Mining,https://example.com,,\n"
    rows=parse_csv_bytes(data)
    assert len(rows)==3
    assert rows[0].exchange_mic=="XTSE" and rows[0].eligible
    assert not rows[1].eligible
    assert rows[2].exchange_mic=="XTSX" and rows[2].eligible

def test_exchange_mics():
    assert normalize_exchange("TSX","RY")=="XTSE"
    assert normalize_exchange("TSX Venture","ABC")=="XTSX"
    assert normalize_exchange("NEX","ABC.H")=="XTNX"

def test_non_company_filter():
    assert not eligible_company("Sample ETF","ETF","",False,"XTSE")
    assert eligible_company("Sample Mining Inc","Common Shares","Mining",False,"XTSX")
