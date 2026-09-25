from __future__ import annotations

from pathlib import Path
import tempfile
import pytest

from africa_ar_bulk.config import RuntimeConfig
from africa_ar_bulk.pipeline import AfricaPipeline
from africa_ar_bulk.models import Candidate
from africa_ar_bulk.zeta import build_final_path, build_staging_path


@pytest.mark.asyncio
async def test_pipeline_staging_and_audit(dummy_pdf_bytes):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        work_dir = root / "local"
        zeta_root = root / "GLOBAL_SUSTAINABILITY_DATABASE"

        cfg = RuntimeConfig(
            work_dir=work_dir,
            zeta_root=zeta_root,
            start_year=2023,
            end_year=2023,
            min_pdf_bytes=1000,
        )

        pipe = AfricaPipeline(cfg)
        try:
            # Stage universe for Nigeria with limit=2
            issuers = pipe.stage_universe(country_iso3="NGA", limit=2)
            assert len(issuers) == 2
            assert all(i.country_iso3 == "NGA" for i in issuers)

            iss = issuers[0]
            # Put dummy pdf into target file
            target_path = build_final_path(zeta_root, iss.country_iso3, iss.exchange_mic, iss.lei or "", iss.isin or "", iss.ticker, 2023)
            if not target_path:
                target_path = build_staging_path(work_dir / "staging", iss.country_iso3, iss.exchange_mic, iss.ticker, 2023)
            
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(dummy_pdf_bytes)

            pipe.db.add_candidate(Candidate(
                candidate_id="cand_test_01",
                issuer_id=iss.issuer_id,
                source_name="EXCHANGE_DIRECT",
                source_url="https://example.com/mock.pdf",
                title=f"{iss.company_name} Annual Report 2023",
                resolved_fy=2023,
                fy_confidence=0.99,
                classification="AR",
                classification_score=0.95,
                direct_pdf_url="https://example.com/mock.pdf",
            ))

            # Run download (should detect local file and verify)
            downloaded = await pipe.download(limit=10)
            assert downloaded == 1

            # Run audit
            stats = pipe.audit()
            assert stats["total_issuers"] == 2
            assert (stats["done_slots"] + stats["staged_slots"]) >= 1
            assert (work_dir / "audit" / "coverage.csv").exists()
            assert (work_dir / "audit" / "issuers.csv").exists()
        finally:
            pipe.close()
