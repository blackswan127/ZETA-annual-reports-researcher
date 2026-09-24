import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fitz

import annual_reports.cli as cli
from annual_reports.catalog import Report
from annual_reports.discovery import Company, DiscoveryStore


def test_live_benchmark_command_with_local_pdf(tmp_path: Path):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "Example annual report 2024")
        pdf = document.tobytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(pdf)))
            self.end_headers()
            self.wfile.write(pdf)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        state_path = tmp_path / "state.sqlite3"
        store = DiscoveryStore(state_path)
        try:
            company = Company("USA", "Example Inc", "XNAS", "2138007ZFQYRUSLU3J98",
                              "US0000000001", "EXM", "320193")
            store.add_universe([company], [2024])
            store.upsert_candidate(company_key=company.key, report_year=2024,
                                   source="SEC", source_record_id="fixture",
                                   source_url=f"http://127.0.0.1:{server.server_port}/annual.pdf",
                                   source_format="pdf", form_type="10-K",
                                   status="DISCOVERED", verified=True)
            store.commit()
        finally:
            store.close()
        result = subprocess.run(
            [sys.executable, "-m", "annual_reports.cli", "benchmark",
             "--state", str(state_path), "--output-root", str(tmp_path / "data"),
             "--limit", "1", "--allow-http"],
            cwd=tmp_path, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        with sqlite3.connect(state_path) as connection:
            count = connection.execute("SELECT COUNT(*) FROM benchmark_runs").fetchone()[0]
        assert count == 1
        assert (tmp_path / "benchmark.csv").is_file()
        assert len(list((tmp_path / "data").rglob("*.pdf"))) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_harvest_batch_downloads_direct_pdf_for_company_cohort(tmp_path: Path, monkeypatch, capsys):
    company = Company("USA", "Example Inc", "XNAS", "2138007ZFQYRUSLU3J98",
                      "US0000000001", "EXM", "320193")
    matching_pdf = Report.from_row({
        "country": company.country, "exchange": company.exchange, "lei": company.lei,
        "isin": company.isin, "ticker": company.ticker, "fiscal_year": "FY2024",
        "report_type": "AR", "language": "EN",
        "pdf_url": "https://www.sec.gov/Archives/example/annual.pdf",
        "source_page": "", "verified": "true",
    })
    same_identifiers_wrong_exchange = Report.from_row({
        "country": company.country, "exchange": "XNYS", "lei": company.lei,
        "isin": company.isin, "ticker": company.ticker, "fiscal_year": "FY2024",
        "report_type": "AR", "language": "EN",
        "pdf_url": "https://www.sec.gov/Archives/example/other.pdf",
        "source_page": "", "verified": "true",
    })
    downloaded = []
    rendered_cohorts = []

    monkeypatch.setattr(cli, "read_universe", lambda _path: [company])
    monkeypatch.setattr(cli, "download_sec_bulk", lambda *_args: tmp_path / "submissions.zip")
    monkeypatch.setattr(cli, "discover_sec_bulk", lambda *_args: {})

    async def no_history(*_args):
        return {}

    def export_manifest(_store, path):
        path.write_text("stub manifest\n", encoding="utf-8")
        return {"pdf_rows": 2}

    monkeypatch.setattr(cli, "discover_sec_history", no_history)
    monkeypatch.setattr(cli, "export_pdf_manifest", export_manifest)
    monkeypatch.setattr(cli, "load_manifest", lambda _path: [
        matching_pdf, same_identifiers_wrong_exchange,
    ])

    async def fake_run(reports, _settings):
        downloaded.extend(reports)
        return {"downloaded": len(reports), "skipped": 0, "failed": 0}

    async def fake_render(*_args, **kwargs):
        rendered_cohorts.append(kwargs["company_keys"])
        return {"pdf_completed": 0, "failed": 0}

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "render_sec_html", fake_render)
    monkeypatch.setattr(cli, "verify_store", lambda *_args: {"ok": True})

    result = cli.main([
        "harvest-batch", str(tmp_path / "cohort.csv"),
        "--state", str(tmp_path / "local" / "state.sqlite3"),
        "--output-root", str(tmp_path / "output"),
        "--cache", str(tmp_path / "cache"),
    ])

    assert result == 0
    assert downloaded == [matching_pdf]
    assert rendered_cohorts == [{company.key}]
    assert '"downloaded": 1' in capsys.readouterr().out


def test_harvest_batch_discovers_and_downloads_uk_fca_cohort(tmp_path: Path, monkeypatch, capsys):
    uk_company = Company("GBR", "Saga PLC", "XLON", "2138004O6UZY9WR66W12",
                         "GB00BSQNQZ79", "SAGA", "")
    fca_pdf = Report.from_row({
        "country": uk_company.country, "exchange": uk_company.exchange, "lei": uk_company.lei,
        "isin": uk_company.isin, "ticker": uk_company.ticker, "fiscal_year": "FY2018",
        "report_type": "AR", "language": "EN",
        "pdf_url": "https://data.fca.org.uk/artefacts/NSM/data-migration/171391686.pdf",
        "source_page": "", "verified": "true",
    })
    downloaded = []
    fca_rendered = []

    monkeypatch.setattr(cli, "read_universe", lambda _path: [uk_company])
    monkeypatch.setattr(cli, "download_sec_bulk", lambda *_args: tmp_path / "submissions.zip")
    monkeypatch.setattr(cli, "discover_sec_bulk", lambda *_args: {})

    async def no_history(*_args):
        return {}

    monkeypatch.setattr(cli, "discover_sec_history", no_history)

    def export_manifest(_store, path):
        path.write_text("stub manifest\n", encoding="utf-8")
        return {"pdf_rows": 1}

    monkeypatch.setattr(cli, "export_pdf_manifest", export_manifest)
    monkeypatch.setattr(cli, "load_manifest", lambda _path: [fca_pdf])

    async def fake_run(reports, _settings):
        downloaded.extend(reports)
        return {"downloaded": len(reports), "skipped": 0, "failed": 0}

    async def fake_render_sec(*_args, **kwargs):
        return {"pdf_completed": 0, "failed": 0}

    async def fake_render_fca(*_args, **kwargs):
        fca_rendered.append(kwargs.get("company_keys"))
        return {"pdf_completed": 0, "failed": 0}

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "render_sec_html", fake_render_sec)
    monkeypatch.setattr(cli, "render_fca_originals", fake_render_fca)
    monkeypatch.setattr(cli, "verify_store", lambda *_args: {"ok": True})

    result = cli.main([
        "harvest-batch", str(tmp_path / "uk_cohort.csv"),
        "--state", str(tmp_path / "local" / "state.sqlite3"),
        "--output-root", str(tmp_path / "output"),
        "--cache", str(tmp_path / "cache"),
    ])

    assert result == 0
    assert downloaded == [fca_pdf]
    assert fca_rendered == [{uk_company.key}]
