from pathlib import Path
import pytest
from pypdf import PdfWriter
from dse_zeta.sources.dse_public import parse_companies_page,parse_company_page,is_equity_issuer,parse_financial_page,require_terms_ack,shard_accept
from dse_zeta.sources.cdbl import parse_cdbl_list
from dse_zeta.classify import is_annual_report,infer_fiscal_year
from dse_zeta.naming import report_filename,company_folder,identity_complete
from dse_zeta.models import Issuer,Candidate
from dse_zeta.identity import apply_cdbl_isin,load_universe_csv
from dse_zeta.db import DB
from dse_zeta.sources.authorized_manifest import load_authorized_manifest
from dse_zeta.downloader import validate_pdf,sha256,fetch_candidate
from dse_zeta.audit import export
from dse_zeta.config import COUNTRY_ISO3,EXCHANGE_MIC,RuntimeConfig
F=Path(__file__).parent/'fixtures'

def make_pdf(path,pages=2):
    w=PdfWriter()
    for _ in range(pages):w.add_blank_page(width=200,height=200)
    with open(path,'wb') as f:w.write(f)

def test_companies_parse():
    r=parse_companies_page((F/'companies.html').read_text(encoding='utf-8',errors='replace'));assert [x[0] for x in r]==['UNITEDFIN','GP','ABBLPBOND']
def test_company_profile_parse():
    i=parse_company_page((F/'company_equity.html').read_text(encoding='utf-8',errors='replace'),'UNITEDFIN');assert i.name=='United Finance PLC.' and i.instrument_type=='Equity' and i.board=='PUBLIC' and i.fiscal_year_end=='December' and 'FinancialReports' in i.financials_url
def test_equity_filter():
    assert is_equity_issuer(parse_company_page((F/'company_equity.html').read_text(encoding='utf-8',errors='replace'),'UNITEDFIN'))
    assert not is_equity_issuer(parse_company_page((F/'company_bond.html').read_text(encoding='utf-8',errors='replace'),'ABBLPBOND'))
def test_financial_page():
    c=parse_financial_page((F/'financials.html').read_text(),'UNITEDFIN','https://issuer.example/reports',2017,2025);assert {(x.fiscal_year,x.title) for x in c}=={(2025,'Annual Report 2024-25'),(2024,'Annual Report 2023-2024')}
def test_classifier():
    assert is_annual_report('Annual Report 2024-25');assert not is_annual_report('Annual Return 2025');assert not is_annual_report('Quarterly Report 2025')
def test_fy_ranges():
    assert infer_fiscal_year('Annual Report 2024-25')[0]==2025;assert infer_fiscal_year('Annual Report 2023-2024')[0]==2024;assert infer_fiscal_year('FY22 Annual Report')[0]==2022
def test_cdbl_parse_and_match():
    rows=parse_cdbl_list((F/'cdbl.html').read_text());assert rows[0][0]=='BD0123UNIFI1';i=Issuer('UNITEDFIN','United Finance PLC.');apply_cdbl_isin([i],rows);assert i.isin=='BD0123UNIFI1'
def test_zeta_constants_and_naming():
    assert COUNTRY_ISO3=='BGD' and EXCHANGE_MIC=='XDHA';lei='5493001KJTIIGC8Y1R12';isin='BD0123UNIFI1';assert identity_complete(lei,isin,'UNITEDFIN');assert company_folder(lei,isin,'UNITEDFIN')==f'{lei}_{isin}_UNITEDFIN';assert report_filename(lei,'UNITEDFIN',isin,2025)==f'{lei}_BGD_XDHA_UNITEDFIN_{isin}_FY2025_AR_EN.pdf'
def test_db_source_priority(tmp_path):
    db=DB(tmp_path/'x.db');db.upsert_issuer(Issuer('ABC','ABC PLC','BD0123456789','5493001KJTIIGC8Y1R12'));db.ensure_slots(2025,2025);db.add_candidate(Candidate('ABC',2025,'Annual Report 2025','https://issuer/ar.pdf','ISSUER_IR',confidence=9));db.add_candidate(Candidate('ABC',2025,'Annual Report 2025','https://auth/ar.pdf','DSE_AUTHORIZED',confidence=6));db.select_best();r=db.conn.execute("SELECT c.source FROM expected_slots s JOIN candidates c ON c.id=s.selected_candidate_id").fetchone();assert r[0]=='DSE_AUTHORIZED';db.close()
def test_authorized_manifest(tmp_path):
    p=tmp_path/'m.csv';p.write_text('ticker,title,fiscal_year,document_url\nABC,Annual Report 2024-25,2025,https://x/ar.pdf\nABC,Annual Return 2025,2025,https://x/return.pdf\n',encoding='utf8');r=load_authorized_manifest(p,2017,2025);assert len(r)==1 and r[0].source=='DSE_AUTHORIZED'
def test_pdf_validation(tmp_path):
    p=tmp_path/'a.pdf';make_pdf(p);assert validate_pdf(p,100)[0] and len(sha256(p))==64;q=tmp_path/'bad.pdf';q.write_text('<html>no</html>');assert not validate_pdf(q,1)[0]
def test_missing_identity_stages(tmp_path):
    src=tmp_path/'src.pdf';make_pdf(src);row={'ticker':'ABC','fiscal_year':2025,'url':str(src),'lei':'','isin':'BD0123456789'}
    class H:pass
    p,_,_,complete=fetch_candidate(H(),row,tmp_path/'root',tmp_path/'stage',100);assert not complete and 'unresolved_identity' in str(p)
def test_complete_identity_final_path(tmp_path):
    src=tmp_path/'src.pdf';make_pdf(src);lei='5493001KJTIIGC8Y1R12';isin='BD0123456789';row={'ticker':'ABC','fiscal_year':2025,'url':str(src),'lei':lei,'isin':isin}
    class H:pass
    p,_,_,complete=fetch_candidate(H(),row,tmp_path/'root',tmp_path/'stage',100);assert complete and Path(p).as_posix().endswith(f'BGD/XDHA/{lei}_{isin}_ABC/FY2025/{lei}_BGD_XDHA_ABC_{isin}_FY2025_AR_EN.pdf')
def test_audit(tmp_path):
    db=DB(tmp_path/'x.db');db.upsert_issuer(Issuer('ABC','ABC PLC','BD0123456789',''));db.ensure_slots(2024,2025);export(db,tmp_path/'audit');assert (tmp_path/'audit/coverage.csv').exists() and (tmp_path/'audit/identity_missing.csv').exists() and (tmp_path/'audit/repair_queue.csv').exists();db.close()
def test_terms_gate(monkeypatch):
    monkeypatch.delenv('DSE_ACKNOWLEDGE_TERMS',raising=False)
    with pytest.raises(RuntimeError):require_terms_ack()
    monkeypatch.setenv('DSE_ACKNOWLEDGE_TERMS','1');require_terms_ack()
def test_universe_csv(tmp_path):
    p=tmp_path/'u.csv';p.write_text('ticker,name,isin,lei,website,financials_url,instrument_type,board,current\nABC,ABC PLC,BD0123456789,5493001KJTIIGC8Y1R12,https://abc.com,https://abc.com/ar,Equity,PUBLIC,1\n',encoding='utf8');r=load_universe_csv(p);assert len(r)==1 and r[0].financials_url.endswith('/ar')
def test_offline_authorized_end_to_end(tmp_path):
    from dse_zeta.pipeline import Pipeline
    pdf=tmp_path/'src.pdf';make_pdf(pdf);u=tmp_path/'u.csv';u.write_text('ticker,name,isin,lei,instrument_type,board,current\nABC,ABC PLC,BD0123456789,5493001KJTIIGC8Y1R12,Equity,PUBLIC,1\n',encoding='utf8');m=tmp_path/'m.csv';m.write_text(f'ticker,title,fiscal_year,local_path\nABC,Annual Report 2024-25,2025,{pdf}\n',encoding='utf8');p=Pipeline(tmp_path/'work',tmp_path/'root',RuntimeConfig(start_year=2025,end_year=2025,min_pdf_bytes=100));p.universe(universe_csv=u);p.ingest_authorized(m);p.download();p.audit();r=p.db.conn.execute("SELECT status,final_path FROM expected_slots").fetchone();assert r['status']=='DONE' and Path(r['final_path']).exists();p.close()
def test_sharding():
    tickers=['GP','UNITEDFIN','SQURPHARMA','WALTONHIL','BRACBANK'];a={t for t in tickers if shard_accept(t,2,0)};b={t for t in tickers if shard_accept(t,2,1)};assert a.isdisjoint(b) and a|b==set(tickers)

def test_obvious_non_equity_prefilter():
    from dse_zeta.sources.dse_public import obvious_non_equity
    assert obvious_non_equity('TB10Y0335A','10Y BGTB 19/03/2035')
    assert obvious_non_equity('ABBLPBOND','AB Bank Perpetual Bond')
    assert not obvious_non_equity('GP','Grameenphone Ltd.')

def test_range_resume_download(tmp_path):
    src=tmp_path/'full.pdf';make_pdf(src);data=src.read_bytes();lei='5493001KJTIIGC8Y1R12';isin='BD0123456789'
    row={'ticker':'ABC','fiscal_year':2025,'url':'https://example/ar.pdf','lei':lei,'isin':isin}
    from dse_zeta.naming import final_path
    target=final_path(tmp_path/'root',lei,isin,'ABC',2025);target.parent.mkdir(parents=True);part=target.with_suffix('.pdf.part');cut=len(data)//2;part.write_bytes(data[:cut])
    class R:
        status_code=206
        def iter_content(self,n):
            yield data[cut:]
    class H:
        def __init__(self):self.headers=[]
        def get(self,url,headers=None,stream=False):self.headers.append(headers or {});return R()
    h=H();p,_,_,complete=fetch_candidate(h,row,tmp_path/'root',tmp_path/'stage',100);assert complete and p.read_bytes()==data and h.headers[0]['Range']==f'bytes={cut}-'
