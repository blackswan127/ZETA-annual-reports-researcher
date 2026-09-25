import csv
def export(conn,work):
 out=work/'audit';out.mkdir(parents=True,exist_ok=True)
 qs={
 'issuers.csv':'SELECT issuer_id,symbol,ticker,name,isin,lei FROM issuers ORDER BY ticker',
 'coverage.csv':'''SELECT i.ticker,i.name,s.fy,s.status,c.title,c.source_url,d.local_path,d.sha256 FROM expected_slots s JOIN issuers i ON i.issuer_id=s.issuer_id LEFT JOIN candidates c ON c.candidate_id=s.selected_candidate_id LEFT JOIN downloads d ON d.candidate_id=s.selected_candidate_id ORDER BY i.ticker,s.fy''',
 'missing.csv':'''SELECT i.ticker,i.name,s.fy,s.status FROM expected_slots s JOIN issuers i ON i.issuer_id=s.issuer_id WHERE s.status IN ('PENDING','MISSING','FAILED','IDENTITY_MISSING') ORDER BY i.ticker,s.fy''',
 'candidates.csv':'''SELECT i.ticker,c.fy,c.fy_confidence,c.title,c.source_url FROM candidates c JOIN issuers i ON i.issuer_id=c.issuer_id ORDER BY i.ticker,c.fy'''}
 for fn,q in qs.items():
  cur=conn.execute(q);rows=cur.fetchall()
  with (out/fn).open('w',newline='',encoding='utf-8-sig') as f:
   w=csv.writer(f);w.writerow([d[0] for d in cur.description]);w.writerows(rows)
