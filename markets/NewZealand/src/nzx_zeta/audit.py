import csv
from pathlib import Path

def _write(path,rows,cols):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows([{c:r[c] if c in r.keys() else "" for c in cols} for r in rows])

def export(db,out:Path):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    issuer_cols=["ticker","name","isin","lei","website","instrument_type","primary_listing_venue","fiscal_year_end","current"]
    issuers=db.conn.execute("SELECT * FROM issuers ORDER BY ticker").fetchall(); _write(out/"issuers.csv",issuers,issuer_cols)
    slots=db.conn.execute("SELECT * FROM expected_slots ORDER BY ticker,fiscal_year").fetchall(); _write(out/"coverage.csv",slots,["ticker","fiscal_year","status","selected_candidate_id","final_path","error"])
    missing=db.conn.execute("SELECT s.*,i.name,i.isin,i.lei,i.website FROM expected_slots s JOIN issuers i USING(ticker) WHERE s.status IN ('MISSING','FAILED') ORDER BY s.ticker,s.fiscal_year").fetchall()
    _write(out/"missing.csv",missing,["ticker","name","isin","lei","website","fiscal_year","status","error"])
    _write(out/"repair_queue.csv",missing,["ticker","name","isin","lei","website","fiscal_year","status","error"])
    ids=db.conn.execute("SELECT * FROM issuers WHERE current=1 AND (length(lei)<>20 OR length(isin)<>12) ORDER BY ticker").fetchall(); _write(out/"identity_missing.csv",ids,issuer_cols)
    cands=db.conn.execute("SELECT * FROM candidates ORDER BY ticker,fiscal_year,confidence DESC").fetchall(); _write(out/"candidates.csv",cands,["id","ticker","fiscal_year","title","url","source","publication_date","announcement_id","confidence"])
    src=db.conn.execute("SELECT * FROM source_profiles ORDER BY priority DESC").fetchall(); _write(out/"source_profiles.csv",src,["source","priority","enabled","health","last_error","updated_at"])
    n=db.conn.execute("SELECT count(*) n FROM issuers WHERE current=1").fetchone()[0]
    done=db.conn.execute("SELECT count(*) n FROM expected_slots WHERE status='DONE'").fetchone()[0]
    total=db.conn.execute("SELECT count(*) n FROM expected_slots").fetchone()[0]
    with (out/"universe_summary.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f); w.writerow(["metric","value"]); w.writerows([["current_equity_issuers",n],["expected_slots",total],["done",done],["coverage_pct",round(done*100/total,2) if total else 0]])
