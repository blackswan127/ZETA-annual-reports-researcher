import csv, os
from pathlib import Path
import pytest
from pypdf import PdfWriter
from nzx_zeta.sources.nzx_public import parse_market_page,parse_company_page,parse_documents_page,parse_announcement_page,is_equity_issuer,require_terms_ack
from nzx_zeta.classify import is_annual_report,annual_report_score,infer_fiscal_year
from nzx_zeta.naming import report_filename,company_folder,identity_complete,final_path
from nzx_zeta.models import Issuer,Candidate
from nzx_zeta.db import DB
from nzx_zeta.sources.authorized_manifest import load_authorized_manifest
from nzx_zeta.downloader import validate_pdf,sha256,fetch_candidate
from nzx_zeta.audit import export
from nzx_zeta.config import COUNTRY_ISO3,EXCHANGE_MIC

F=Path(__file__).parent/'fixtures'

def test_market_parse(): assert parse_market_page((F/'market.html').read_text())[:2]==[('NZX','NZX Limited'),('CEN','Contact Energy Limited')]
def test_company_parse():
    i=parse_company_page((F/'company.html').read_text(),'NZX'); assert i.isin=='NZNZXE0001S7' and i.instrument_type=='Ordinary Shares' and i.fiscal_year_end=='December'
def test_equity_filter():
    assert is_equity_issuer(parse_company_page((F/'company.html').read_text(),'NZX'))
    assert not is_equity_issuer(parse_company_page((F/'fund.html').read_text(),'AGG'))
def test_documents_parse():
    c=parse_documents_page((F/'documents.html').read_text(),'NZX',2017,2025); assert {(x.fiscal_year,x.title) for x in c}=={(2025,'Annual Report - 2025'),(2024,'Annual Report - 2024')}
def test_announcement_parse():
    c=parse_announcement_page((F/'announcement.html').read_text(),'NZX'); assert c and c[0].fiscal_year==2025 and c[0].source=='NZX_ANNREP'
def test_classifier_rejects_false_positive():
    assert not is_annual_report('2025 Interim Report')
    assert not is_annual_report('2025 Annual Meeting Presentation')
    assert is_annual_report('2025 Annual Report')
    assert is_annual_report('Release', 'ANNREP','Annual report for year ended 31 March 2025')
def test_fy_inference():
    assert infer_fiscal_year('FY25 Annual Report')[0]==2025
    assert infer_fiscal_year('Annual Report','for the year ended 31 March 2024')[0]==2024
    assert infer_fiscal_year('Annual Report - 2019')[0]==2019
def test_zeta_naming():
    lei='5493001KJTIIGC8Y1R12'; isin='NZNZXE0001S7'; fn=report_filename(lei,'NZX',isin,2025)
    assert fn=='5493001KJTIIGC8Y1R12_NZL_XNZE_NZX_NZNZXE0001S7_FY2025_AR_EN.pdf'
    assert company_folder(lei,isin,'NZX')=='5493001KJTIIGC8Y1R12_NZNZXE0001S7_NZX'
    assert identity_complete(lei,isin,'NZX')
def test_constants(): assert COUNTRY_ISO3=='NZL' and EXCHANGE_MIC=='XNZE'
def test_db_slots_and_best_source(tmp_path):
    db=DB(tmp_path/'x.sqlite3'); db.upsert_issuer(Issuer('NZX','NZX Limited','NZNZXE0001S7','5493001KJTIIGC8Y1R12')); db.ensure_slots(2024,2025)
    db.add_candidate(Candidate('NZX',2025,'Annual Report 2025','https://issuer/ar.pdf','ISSUER_IR',confidence=9))
    db.add_candidate(Candidate('NZX',2025,'Annual Report 2025','https://licensed/ar.pdf','NZX_AUTHORIZED',confidence=7)); db.select_best()
    r=db.conn.execute("SELECT c.source FROM expected_slots s JOIN candidates c ON c.id=s.selected_candidate_id WHERE s.ticker='NZX' AND s.fiscal_year=2025").fetchone(); assert r[0]=='NZX_AUTHORIZED'; db.close()
def test_authorized_manifest(tmp_path):
    p=tmp_path/'m.csv'; p.write_text('ticker,title,fiscal_year,document_url,announcement_type\nNZX,Annual Report 2025,2025,https://x/ar.pdf,ANNREP\nNZX,Interim Report 2025,2025,https://x/int.pdf,INTERIM\n',encoding='utf8')
    r=load_authorized_manifest(p,2017,2025); assert len(r)==1 and r[0].source=='NZX_AUTHORIZED'
def make_pdf(path,pages=2):
    w=PdfWriter(); [w.add_blank_page(width=200,height=200) for _ in range(pages)];
    with open(path,'wb') as f:w.write(f)
def test_pdf_validation(tmp_path):
    p=tmp_path/'a.pdf'; make_pdf(p); ok,why=validate_pdf(p,100); assert ok and len(sha256(p))==64
    q=tmp_path/'bad.pdf'; q.write_text('<html>no</html>'); assert not validate_pdf(q,1)[0]
def test_local_ingest_stages_when_identity_missing(tmp_path):
    src=tmp_path/'src.pdf'; make_pdf(src)
    row={'ticker':'ABC','fiscal_year':2025,'url':str(src),'lei':'','isin':'NZABC0000001'}
    class H: pass
    p,h,n,complete=fetch_candidate(H(),row,tmp_path/'zeta',tmp_path/'stage',100); assert p.exists() and not complete and 'unresolved_identity' in str(p)
def test_local_ingest_final_zeta(tmp_path):
    src=tmp_path/'src.pdf'; make_pdf(src); lei='5493001KJTIIGC8Y1R12'; isin='NZNZXE0001S7'
    row={'ticker':'NZX','fiscal_year':2025,'url':str(src),'lei':lei,'isin':isin}
    class H: pass
    p,h,n,complete=fetch_candidate(H(),row,tmp_path/'zeta',tmp_path/'stage',100); assert complete and Path(p).as_posix().endswith('NZL/XNZE/5493001KJTIIGC8Y1R12_NZNZXE0001S7_NZX/FY2025/5493001KJTIIGC8Y1R12_NZL_XNZE_NZX_NZNZXE0001S7_FY2025_AR_EN.pdf')
def test_audit(tmp_path):
    db=DB(tmp_path/'x.db'); db.upsert_issuer(Issuer('NZX','NZX Limited','NZNZXE0001S7','')); db.ensure_slots(2024,2025); export(db,tmp_path/'audit')
    assert (tmp_path/'audit/coverage.csv').exists() and (tmp_path/'audit/identity_missing.csv').exists() and (tmp_path/'audit/repair_queue.csv').exists(); db.close()
def test_terms_gate(monkeypatch):
    monkeypatch.delenv('NZX_ACKNOWLEDGE_TERMS',raising=False)
    with pytest.raises(RuntimeError): require_terms_ack()
    monkeypatch.setenv('NZX_ACKNOWLEDGE_TERMS','1'); require_terms_ack()

def test_load_authorized_universe(tmp_path):
    from nzx_zeta.identity import load_universe_csv
    p=tmp_path/'u.csv'; p.write_text('ticker,name,isin,lei,website,instrument_type,primary_listing_venue,fiscal_year_end,current\nNZX,NZX Limited,NZNZXE0001S7,5493001KJTIIGC8Y1R12,https://www.nzx.com,Ordinary Shares,NZ,December,1\n',encoding='utf8')
    r=load_universe_csv(p); assert len(r)==1 and r[0].ticker=='NZX' and r[0].current

def test_offline_authorized_end_to_end(tmp_path):
    from nzx_zeta.pipeline import Pipeline
    from nzx_zeta.config import RuntimeConfig
    pdf=tmp_path/'source.pdf'; make_pdf(pdf)
    universe=tmp_path/'u.csv'; universe.write_text('ticker,name,isin,lei,website,instrument_type,primary_listing_venue,fiscal_year_end,current\nNZX,NZX Limited,NZNZXE0001S7,5493001KJTIIGC8Y1R12,,Ordinary Shares,NZ,December,1\n',encoding='utf8')
    manifest=tmp_path/'m.csv'; manifest.write_text(f'ticker,title,fiscal_year,local_path,announcement_type\nNZX,Annual Report 2025,2025,{pdf},ANNREP\n',encoding='utf8')
    p=Pipeline(tmp_path/'work',tmp_path/'root',RuntimeConfig(start_year=2025,end_year=2025,min_pdf_bytes=100))
    p.universe(universe_csv=universe); p.ingest_authorized(manifest); p.download(); p.audit()
    row=p.db.conn.execute("SELECT status,final_path FROM expected_slots WHERE ticker='NZX' AND fiscal_year=2025").fetchone(); assert row['status']=='DONE' and Path(row['final_path']).exists()
    p.close(); assert (tmp_path/'work/audit/coverage.csv').exists()

def test_sharding_is_deterministic_and_disjoint():
    from nzx_zeta.sources.nzx_public import shard_accept
    tickers=['NZX','CEN','AIR','SPK','IFT','FBU','MFT','RYM']
    a={t for t in tickers if shard_accept(t,2,0)}; b={t for t in tickers if shard_accept(t,2,1)}
    assert a.isdisjoint(b) and a|b==set(tickers)
