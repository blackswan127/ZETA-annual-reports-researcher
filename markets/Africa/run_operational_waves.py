from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Add package root to sys.path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from africa_ar_bulk.config import RuntimeConfig
from africa_ar_bulk.pipeline import AfricaPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("africa_waves")

WAVES = [
    {
        "name": "Wave 3 (South Africa Harvest)",
        "countries": ["ZAF"],
    },
]


async def run_country(pipe: AfricaPipeline, country_iso3: str) -> dict:
    t0 = time.time()
    logger.info(f"=== Starting Harvest for {country_iso3} ===")
    
    # 1. Stage universe (guarantees both AR & SR slots exist for 2017-2025)
    issuers = pipe.stage_universe(country_iso3=country_iso3, report_types=("AR", "SR"))
    logger.info(f"[{country_iso3}] Staged {len(issuers)} active issuers")
    
    # 2. Discover candidates across 3-tier waterfall
    logger.info(f"[{country_iso3}] Discovering candidates (AfricanFinancials + Direct Exchange + Issuer IR)...")
    discovered = await pipe.discover(issuers=issuers)
    logger.info(f"[{country_iso3}] Discovered {discovered} candidates")
    
    # 3. Download and validate best candidates into Google Drive (GLOBAL_SUSTAINABILITY_DATABASE)
    logger.info(f"[{country_iso3}] Downloading and validating candidates with PyMuPDF...")
    downloaded = await pipe.download(country_iso3=country_iso3)
    logger.info(f"[{country_iso3}] Successfully downloaded and promoted {downloaded} files to Google Drive")
    
    elapsed = round(time.time() - t0, 1)
    logger.info(f"=== Completed {country_iso3} in {elapsed}s ===")
    return {
        "country": country_iso3,
        "issuers": len(issuers),
        "discovered": discovered,
        "downloaded": downloaded,
        "elapsed_sec": elapsed,
    }


async def main():
    zeta_root = Path(os.environ.get("ZETA_ROOT", "GLOBAL_SUSTAINABILITY_DATABASE"))
    work_dir = Path("work")

    cfg = RuntimeConfig(
        start_year=2017,
        end_year=2025,
        discovery_workers=16,
        download_workers=24,
        discovery_rps=8.0,
        download_rps=15.0,
        timeout=25.0,
        retries=3,
        min_pdf_bytes=25000,
        work_dir=work_dir,
        zeta_root=zeta_root,
    )

    pipe = AfricaPipeline(cfg)
    total_start = time.time()
    all_results = []

    try:
        logger.info("================================================================")
        logger.info("   PAN-AFRICAN ANNUAL & SUSTAINABILITY REPORTS HARVESTER")
        logger.info("   16 Countries | FY2017 - FY2025 | Target: Google Drive")
        logger.info("================================================================")

        for wave_idx, wave in enumerate(WAVES, start=1):
            wave_name = wave["name"]
            countries = wave["countries"]
            logger.info(f"\n>>>>>>>> STARTING {wave_name} <<<<<<<<")
            logger.info(f"Countries: {', '.join(countries)}")

            for country in countries:
                try:
                    res = await run_country(pipe, country)
                    all_results.append(res)
                except Exception as e:
                    logger.error(f"Error during {country} harvest: {e}", exc_info=True)
                # Export incremental audit after each country
                pipe.audit()

            logger.info(f">>>>>>>> FINISHED {wave_name} <<<<<<<<\n")

        # Final audit
        final_stats = pipe.audit()
        total_time = round(time.time() - total_start, 1)

        logger.info("================================================================")
        logger.info(f"   PAN-AFRICAN HARVEST COMPLETE IN {total_time}s")
        logger.info("================================================================")
        for k, v in final_stats.items():
            logger.info(f"  {k}: {v}")

    finally:
        pipe.close()


if __name__ == "__main__":
    asyncio.run(main())
