from .util import safe_component
ISO3='LKA';MIC='XCOL'
def final_path(root,lei,isin,ticker,fy,report_type='AR'):
 if not lei or not isin:return None
 company=f'{safe_component(lei)}_{safe_component(isin)}_{safe_component(ticker)}'
 name=f'{safe_component(lei)}_{ISO3}_{MIC}_{safe_component(ticker)}_{safe_component(isin)}_FY{fy}_{report_type}_EN.pdf'
 return root/ISO3/MIC/company/f'FY{fy}'/name
def staging_path(root,ticker,fy,report_type='AR'):return root/ISO3/'staging'/'unresolved_identity'/safe_component(ticker)/f'FY{fy}'/f'{safe_component(ticker)}_FY{fy}_{report_type}_EN.pdf'
