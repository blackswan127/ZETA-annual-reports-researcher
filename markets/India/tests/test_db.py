from pathlib import Path
from india_ar_bulk.db import Database
from india_ar_bulk.models import Issuer,Candidate

def test_db_prefers_nse(tmp_path):
    db=Database(tmp_path/'x.db'); i=Issuer('INE1','INE1','Test',nse_symbol='TEST',bse_scrip='500001',source_flags='BSE,NSE'); db.replace_universe([i],{'deduped':1}); db.init_slots(2025,2025)
    db.add_candidates([Candidate('INE1',2025,'BSE_PAGE','b','Annual Report','http://b.pdf',score=999), Candidate('INE1',2025,'NSE','n','Annual Report','http://n.pdf',score=200)])
    db.select_best(2025,2025); r=db.conn.execute('select c.source from expected_slots e join candidates c on c.id=e.selected_candidate_id').fetchone(); assert r[0]=='NSE'; db.close()

def test_audit_files(tmp_path):
    db=Database(tmp_path/'x.db'); db.replace_universe([Issuer('K','','Test',nse_symbol='T')],{'nse_raw':1,'deduped':1}); db.init_slots(2025,2025); db.export_audits(tmp_path/'audit'); assert (tmp_path/'audit/coverage.csv').exists() and (tmp_path/'audit/universe_summary.csv').exists(); db.close()
