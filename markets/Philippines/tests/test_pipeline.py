import asyncio
import sqlite3
import pytest
from pathlib import Path

from phl_pse_bulk.config import Settings
from phl_pse_bulk.contract import PSESlot
from phl_pse_bulk.pipeline import HarvestPipeline


def test_sqlite_state_initialization(tmp_path: Path):
    settings = Settings(
        local_dir=tmp_path / "local",
        output_root=tmp_path / "output",
        acknowledge_terms=True,
    )
    pipeline = HarvestPipeline(settings)

    # Check that database and table were created
    assert settings.state_db.exists()
    with sqlite3.connect(settings.state_db) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='harvest_slots'")
        assert cursor.fetchone() is not None

    # Test saving slot state
    slot = PSESlot(
        issuer_id="AC",
        fiscal_year=2024,
        report_type="AR",
        status="PROMOTED",
        destination_path=str(tmp_path / "AC.pdf"),
        sha256="abcd1234abcd1234",
        page_count=120,
        file_size_bytes=5000000,
        reason="Promoted successfully",
    )
    pipeline._save_slot_state(slot)

    with sqlite3.connect(settings.state_db) as conn:
        row = conn.execute("SELECT issuer_id, fiscal_year, status, page_count FROM harvest_slots WHERE issuer_id='AC'").fetchone()
        assert row is not None
        assert row[0] == "AC"
        assert row[1] == 2024
        assert row[2] == "PROMOTED"
        assert row[3] == 120

    asyncio.run(pipeline.close())
