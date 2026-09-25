from pathlib import Path
from canada_zeta_bulk.sedar_manifest import import_candidates

def test_sedar_authorized_manifest_import(tmp_path):
    p=tmp_path/"sedar.csv"
    p.write_text("issuer_name,ticker,exchange_mic,document_type,document_url,period_end,language,document_id\nRoyal Bank of Canada,RY,XTSE,Annual Report,https://licensed.example/ry2024.pdf,2024-10-31,English,abc\nRoyal Bank of Canada,RY,XTSE,Annual Information Form,https://licensed.example/aif.pdf,2024-10-31,English,def\n",encoding="utf-8")
    issuers=[{"issuer_key":"XTSE:RY","name":"Royal Bank of Canada","ticker":"RY","exchange_mic":"XTSE","isin":"CA7800871021","lei":""}]
    c,u=import_candidates(p,issuers,2017,2025)
    assert len(c)==1 and c[0].fiscal_year==2024 and c[0].source=="SEDAR_DDS"
    assert not u

def test_sedar_unmatched_is_not_guessed(tmp_path):
    p=tmp_path/"sedar.csv"
    p.write_text("issuer_name,document_type,document_url,period_end\nUnknown Corp,Annual Report,https://x/u.pdf,2024-12-31\n",encoding="utf-8")
    issuers=[{"issuer_key":"XTSE:RY","name":"Royal Bank of Canada","ticker":"RY","exchange_mic":"XTSE","isin":"","lei":""}]
    c,u=import_candidates(p,issuers,2017,2025)
    assert len(c)==0 and len(u)==1

def test_local_manifest_path_becomes_file_uri(tmp_path):
    from canada_zeta_bulk.sedar_manifest import import_candidates
    pdf=tmp_path/'annual_2024.pdf'; pdf.write_bytes(b'%PDF-1.4\n')
    m=tmp_path/'m.csv'
    m.write_text('issuer_name,document_title,document_path,period_end\nABC Corp,2024 Annual Report,annual_2024.pdf,2024-12-31\n',encoding='utf-8')
    issuers=[{'issuer_key':'XTSE:ABC','name':'ABC Corp','ticker':'ABC','exchange_mic':'XTSE','isin':'','lei':''}]
    c,u=import_candidates(m,issuers,2017,2025)
    assert len(c)==1 and c[0].url.startswith('file:') and not u
