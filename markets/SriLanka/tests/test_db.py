from lka_cse_bulk.db import DB
from lka_cse_bulk.cse import Issuer,Candidate

def test_slots_candidate(tmp_path):
 db=DB(tmp_path/'x.db');i=Issuer('i','ABC.N0000','ABC','ABC PLC');db.upsert_issuer(i);db.make_slots('i',2017,2018);db.add_candidate(Candidate('c','i','ABC.N0000',2017,.98,'AR 2017','https://x/a.pdf',{}));assert db.conn.execute("select status from expected_slots where fy=2017").fetchone()[0]=='FOUND';db.close()
def test_best_confidence(tmp_path):
 db=DB(tmp_path/'x.db');i=Issuer('i','ABC.N0000','ABC','ABC PLC');db.upsert_issuer(i);db.make_slots('i',2024,2024);db.add_candidate(Candidate('c1','i','ABC.N0000',2024,.7,'AR','https://x/1.pdf',{}));db.add_candidate(Candidate('c2','i','ABC.N0000',2024,.99,'Annual Report 2024','https://x/2.pdf',{}));assert db.conn.execute('select selected_candidate_id from expected_slots').fetchone()[0]=='c2';db.close()
