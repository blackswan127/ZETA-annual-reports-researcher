from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add Singapore src and root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "markets" / "Singapore" / "src"))
sys.path.insert(0, str(ROOT_DIR))

from sgx_bulk.pipeline import Pipeline
from sgx_bulk.models import Issuer
from markets._integration.promotion import (
    promote_pdf_to_corpus,
    compute_sha256_and_size,
    validate_pdf_bytes_or_file,
    is_valid_lei,
    is_valid_isin,
)


async def main() -> int:
    t_start = time.time()
    work_dir = ROOT_DIR / "local" / "markets" / "Singapore" / "work"
    corpus_root = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"
    staging_root = ROOT_DIR / "local" / "markets" / "Singapore" / "staging"
    audit_dir = work_dir / "audit"

    print("=" * 75)
    print("SGX FULL UNIVERSE ANNUAL & SUSTAINABILITY HARVESTER (FY2017 - FY2025)")
    print(f"Target Output Corpus: {corpus_root}")
    print(f"Local State DB:       {work_dir / 'manifest.sqlite3'}")
    print(f"Start Time:           {datetime.now(timezone.utc).isoformat()}")
    print("=" * 75)

    pipe = Pipeline(
        output=work_dir,
        start_year=2017,
        end_year=2025,
        discovery_workers=8,
        detail_workers=10,
        download_workers=8,
        targeted_recovery=True,
    )

    try:
        # Step 1: Discover
        print("\n[PHASE 1/5] Discovering all current issuers and filings (2017-2025)...")
        issuers_count, filings_count = await pipe.discover()
        print(f"  --> Discovered: {issuers_count} current issuers, {filings_count} total filings in DB.")

        # Step 2: Resolve attachments
        print("\n[PHASE 2/5] Resolving attachments for filings...")
        resolved_ok, resolved_fail = await pipe.resolve()
        print(f"  --> Attachments resolved: {resolved_ok} valid, {resolved_fail} unresolvable.")

        # Step 3: Download
        print("\n[PHASE 3/5] Downloading selected report PDFs...")
        dl_ok, dl_fail = await pipe.download()
        print(f"  --> Download phase completed: {dl_ok} succeeded/verified, {dl_fail} failed.")

        # Step 4: Audit exports
        print("\n[PHASE 4/5] Generating audit CSV reports...")
        pipe.audit()
        print(f"  --> Audit reports written to: {audit_dir}")

        # Step 5: SOP Promotion to Google Drive (GLOBAL_SUSTAINABILITY_DATABASE)
        print("\n[PHASE 5/5] Promoting validated PDFs to SOP corpus (Google Drive / Staging)...")
        conn = pipe.db.conn
        conn.row_factory = __import__("sqlite3").Row

        # Load issuers map
        issuer_rows = conn.execute("SELECT * FROM issuers").fetchall()
        issuers_by_ibm = {r["ibm_code"]: r for r in issuer_rows}

        completed_attachments = conn.execute(
            """SELECT a.local_path, a.filename, f.ibm_code, f.stock_code, f.issuer_name,
                      f.fiscal_year, f.report_type, f.announcement_id
               FROM attachments a JOIN filings f USING(announcement_id)
               WHERE a.selected=1 AND a.status='done' AND a.local_path IS NOT NULL"""
        ).fetchall()

        promoted_count = 0
        idempotent_count = 0
        staged_count = 0
        failed_promo = 0

        for att in completed_attachments:
            src_pdf = Path(att["local_path"])
            if not src_pdf.exists():
                continue

            ibm = att["ibm_code"]
            issuer_meta = issuers_by_ibm.get(ibm)
            isin = issuer_meta["isin"] if issuer_meta and issuer_meta["isin"] else ""
            ticker = att["stock_code"] or ibm
            fy = int(att["fiscal_year"])
            rtype = att["report_type"] or "AR"

            status, reason, final_p = promote_pdf_to_corpus(
                source_pdf=src_pdf,
                output_root=corpus_root,
                staging_root=staging_root,
                iso3="SGP",
                mic="XSES",
                ticker=ticker,
                fiscal_year=fy,
                lei="",  # Leave empty if not yet resolved; stages safely to staging/unresolved_identity
                isin=isin,
                report_type=rtype,
            )

            if status == "PROMOTED":
                promoted_count += 1
            elif status == "IDEMPOTENT_EXISTING":
                idempotent_count += 1
            elif status == "STAGED_UNRESOLVED_IDENTITY":
                staged_count += 1
            else:
                failed_promo += 1

        elapsed = time.time() - t_start
        print("\n" + "=" * 75)
        print("SGX HARVESTING EXECUTION AUDIT SUMMARY")
        print("=" * 75)
        print(f"Current Issuers:          {len(issuer_rows)}")
        print(f"Target Fiscal Years:      2017 - 2025")
        print(f"Total Discovered Filings: {filings_count}")
        print(f"Downloads Completed:      {dl_ok}")
        print(f"Downloads Failed:         {dl_fail}")
        print(f"Promoted to SOP Corpus:   {promoted_count}")
        print(f"Idempotent in Corpus:     {idempotent_count}")
        print(f"Staged (Pending LEI):     {staged_count}")
        print(f"Elapsed Time:             {elapsed:.1f}s ({elapsed/60.0:.2f} min)")
        print(f"Final Output Corpus:      {corpus_root}")
        print(f"Staging Directory:        {staging_root}")
        print(f"Audit CSVs Directory:     {audit_dir}")
        print("=" * 75 + "\n")

    finally:
        await pipe.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
