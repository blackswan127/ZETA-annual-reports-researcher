from datetime import UTC, date, datetime

from sgx_bulk.db import Database
from sgx_bulk.models import Attachment, Filing, Issuer


def test_db_resume_state(tmp_path):
    db = Database(tmp_path / "m.sqlite3")
    issuer = Issuer("1J26", "S68", "SINGAPORE EXCHANGE LIMITED", "SGX", "MAINBOARD")
    db.upsert_issuers([issuer])
    f = Filing("2J4PCEOQYA3WTBWP", "1J26", "S68", issuer.issuer_name, "SGX", 2025,
               date(2025,6,30), datetime(2025,9,15,tzinfo=UTC),
               "https://links.sgx.com/1.0.0/corporate-announcements/2J4PCEOQYA3WTBWP/" + "a"*64)
    db.upsert_filing(f, "global", "companyName")
    a = Attachment(f.announcement_id, "https://links.sgx.com/1.0.0/corporate-announcements/2J4PCEOQYA3WTBWP/1_AR.pdf", "1_AR.pdf", 120)
    db.replace_attachments(f.announcement_id, [a], {a.url})
    rows = db.selected_downloads()
    assert len(rows) == 1
    db.mark_download(a.url, status="done", local_path="x.pdf", size_bytes=1234, sha256="abc")
    assert db.selected_downloads() == []
    db.close()
