from lka_cse_bulk.fy import resolve_fy
from lka_cse_bulk.cse import CSEClient
from lka_cse_bulk.util import base_ticker,prefer_symbol
from lka_cse_bulk.zeta import final_path

def test_fy_year():assert resolve_fy({'fileText':'Annual Report 2024'})[0]==2024
def test_fy_range():assert resolve_fy({'fileText':'Annual Report 2024/2025'})[0]==2025
def test_fy_short():assert resolve_fy({'title':'Annual Report 2023-24'})[0]==2024
def test_no_year():assert resolve_fy({'title':'Annual Report'})[0] is None
def test_base():assert base_ticker('JKH.N0000')=='JKH'
def test_prefer():assert prefer_symbol(['ABC.X0000','ABC.N0000'])=='ABC.N0000'
def test_modern():assert CSEClient.normalize_cdn_url('cmt/upload_report_file/a.pdf',2024)=='https://cdn.cse.lk/cmt/upload_report_file/a.pdf'
def test_legacy():assert CSEClient.normalize_cdn_url('upload_report_file/a.pdf',2017)=='https://cdn.cse.lk/cmt/upload_report_file/a.pdf'
def test_absolute():assert CSEClient.normalize_cdn_url('https://cdn.cse.lk/cmt/a.pdf',2017)=='https://cdn.cse.lk/cmt/a.pdf'
def test_zeta_requires_id(tmp_path):assert final_path(tmp_path,None,'LK000','ABC',2024) is None
def test_zeta_path(tmp_path):
 p=final_path(tmp_path,'12345678901234567890','LK0000000000','ABC',2024);s=str(p);assert 'LKA' in s and 'XCOL' in s and 'FY2024' in s and s.endswith('_AR_EN.pdf')
