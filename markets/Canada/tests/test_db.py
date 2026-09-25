from pathlib import Path
from canada_zeta_bulk.db import Database
from canada_zeta_bulk.models import Issuer, Candidate

def setup(tmp_path):
    db=Database(tmp_path/"x.sqlite3")
    db.upsert_issuers([Issuer("XTSE:ABC","ABC Corp","ABC","XTSE",isin="CA0000000001",lei="LEI00000000000000001")])
    db.init_slots(2024,2025)
    return db

def test_expected_slots(tmp_path):
    db=setup(tmp_path)
    assert db.conn.execute("select count(*) from expected_slots").fetchone()[0]==2
    db.close()

def test_source_priority_selection(tmp_path):
    db=setup(tmp_path)
    db.add_candidates([
      Candidate("XTSE:ABC",2024,"2024 Annual Report","https://issuer/a.pdf","ISSUER_SITE",2,score=100),
      Candidate("XTSE:ABC",2024,"Annual Report","https://licensed/a.pdf","SEDAR_DDS",1,score=80),
    ])
    db.select_best(2024,2025)
    row=db.conn.execute("select source from candidates where selected=1").fetchone()
    assert row[0]=="SEDAR_DDS"
    db.close()

def test_identity_override(tmp_path):
    db=Database(tmp_path/"x.sqlite3")
    db.upsert_issuers([Issuer("XTSX:JMN","Junior Mine","JMN","XTSX")])
    assert db.apply_identity_overrides([{"ticker":"JMN","exchange_mic":"XTSX","lei":"L123","isin":"CA123"}])==1
    r=db.conn.execute("select lei,isin from issuers").fetchone(); assert tuple(r)==("L123","CA123")
    db.close()

def test_audit_exports_universe_and_repair_queue(tmp_path):
    db=setup(tmp_path)
    out=tmp_path/'audit'
    db.export_audits(out)
    assert (out/'universe_summary.csv').exists()
    assert 'XTSE' in (out/'universe_summary.csv').read_text(encoding='utf-8-sig')
    assert (out/'repair_queue.csv').exists()
    assert 'ABC' in (out/'repair_queue.csv').read_text(encoding='utf-8-sig')
    db.close()
