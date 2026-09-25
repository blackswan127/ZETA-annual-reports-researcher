from india_ar_bulk.parsers import parse_nse_csv,parse_nse_annual_json,parse_bse_list,merge_issuers,parse_bse_annual_html

def test_nse_csv():
    text='SYMBOL,NAME OF COMPANY,SERIES,ISIN NUMBER\nRELIANCE,Reliance Industries Limited,EQ,INE002A01018\n'
    r=parse_nse_csv(text); assert len(r)==1 and r[0].nse_symbol=='RELIANCE' and r[0].isin=='INE002A01018'

def test_nse_annual_json_pdf_and_zip():
    p={'data':[{'fromYr':'2024','toYr':'2025','submission_type':'Annual Report','fileName':'https://x/a.pdf','broadcast_dttm':'01-07-2025'}, {'fromYr':'2022','toYr':'2023','submission_type':'Annual Report','fileName':'https://x/a.zip'}]}
    x=parse_nse_annual_json('INE002A01018',p); assert [c.fiscal_year for c in x]==[2025,2023]; assert x[1].file_kind=='ZIP'

def test_bse_list_and_merge_by_isin():
    b=parse_bse_list({'Table':[{'SCRIP_CD':'500325','Scrip_Name':'Reliance Industries Ltd','ISIN_NUMBER':'INE002A01018','GROUP':'A'}]})
    n=parse_nse_csv('SYMBOL,NAME OF COMPANY,SERIES,ISIN NUMBER\nRELIANCE,Reliance Industries Limited,EQ,INE002A01018\n')
    m=merge_issuers(n,b); assert len(m)==1 and m[0].nse_symbol=='RELIANCE' and m[0].bse_scrip=='500325'

def test_bse_annual_html_legacy_year():
    h='<table><tr><td>Annual Report</td><td><a href="https://www.bseindia.com/bseplus/AnnualReport/500325/5003250319.pdf">Download</a></td></tr></table>'
    x=parse_bse_annual_html('K',h); assert len(x)==1 and x[0].fiscal_year==2019 and x[0].source=='BSE_PAGE'
