from datetime import date
from pathlib import Path
from asx_bulk.db import Database
from asx_bulk.models import Filing, Issuer

def filing(ticker, ann, title, score, pages=50, fy=2025):
    return Filing(ticker=ticker,published_date=date(2025,9,1),title=title,
                  display_url=f"https://x/?idsId={ann}",announcement_id=ann,pages=pages,
                  size_text="1MB",source_year=2025,fiscal_year=fy,year_method="title_year",score=score)

def test_database_selection_and_audit(tmp_path: Path):
    db = Database(tmp_path / "x.sqlite3")
    db.upsert_issuers([Issuer("AAA", "Alpha Ltd")])
    db.init_slots(2025, 2025)
    db.add_filings([
        filing("AAA","1","Annual Report 2025",90,50),
        filing("AAA","2","Annual Report and Financial Statements 2025",110,100),
    ])
    db.select_best(2025, 2025)
    row = db.conn.execute("select * from expected_slots").fetchone()
    assert row["status"] == "FOUND"
    assert row["candidate_count"] == 2
    selected = db.conn.execute("select title from filings where selected=1").fetchone()[0]
    assert "Financial Statements" in selected
    db.export_audits(tmp_path / "audit")
    assert (tmp_path / "audit" / "coverage.csv").exists()
    db.close()

def test_universe_refresh_deactivates_removed_tickers_but_keeps_history(tmp_path: Path):
    db = Database(tmp_path / "refresh.sqlite3")
    db.upsert_issuers([Issuer("AAA", "Alpha Ltd"), Issuer("BBB", "Beta Ltd")])
    db.init_slots(2025, 2025)
    db.upsert_issuers([Issuer("AAA", "Alpha Ltd (renamed)")])
    active = db.conn.execute("SELECT ticker FROM issuers WHERE active=1").fetchall()
    assert [row[0] for row in active] == ["AAA"]
    # Existing issuer history stays stored, but selection/audits are current-universe scoped.
    assert db.conn.execute("SELECT COUNT(*) FROM issuers").fetchone()[0] == 2
    db.select_best(2025, 2025)
    assert [row[0] for row in db.conn.execute(
        """SELECT DISTINCT e.ticker FROM expected_slots e JOIN issuers i USING(ticker)
           WHERE i.active=1 AND e.status='MISSING'"""
    )] == ["AAA"]
    db.close()
