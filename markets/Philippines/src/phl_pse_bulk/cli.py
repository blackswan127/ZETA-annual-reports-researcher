from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import List, Optional
import click

from .config import Settings
from .pipeline import HarvestPipeline
from .universe import BENCHMARK_SMOKE_TICKERS, UniverseManager


@click.group()
def main():
    """Philippines PSE Annual & Sustainability Report Harvesting CLI."""
    pass


@main.command()
@click.option("--acknowledge-terms", is_flag=True, help="Acknowledge PSE terms")
@click.option("--refresh", is_flag=True, help="Refresh universe cache from PSE")
def universe(acknowledge_terms: bool, refresh: bool):
    """Fetch and display active PSE listed companies."""
    if acknowledge_terms:
        os.environ["PSE_TERMS_ACKNOWLEDGED"] = "1"
    settings = Settings()
    mgr = UniverseManager(settings)

    async def _run():
        issuers = await mgr.fetch_universe(refresh=refresh)
        click.echo(f"Active PSE Listed Issuers: {len(issuers)}")
        for iss in issuers[:15]:
            click.echo(f"  {iss.ticker:<8} | {iss.company_name:<40} | LEI: {iss.lei or 'NOLEI'} | ISIN: {iss.isin or 'NOISIN'}")
        if len(issuers) > 15:
            click.echo(f"  ... and {len(issuers) - 15} more.")

    asyncio.run(_run())


@main.command()
@click.option("--years", default="2017-2025", help="Fiscal years (e.g. 2017-2025 or 2024)")
@click.option("--types", default="AR,SR", help="Report types (AR, SR, or AR,SR)")
@click.option("--max-issuers", type=int, default=None, help="Limit number of issuers")
@click.option("--tickers", default="", help="Comma-separated ticker list")
@click.option("--acknowledge-terms", is_flag=True, help="Acknowledge PSE terms")
@click.option("--output-root", default="GLOBAL_SUSTAINABILITY_DATABASE", help="Target corpus directory")
def run(years: str, types: str, max_issuers: Optional[int], tickers: str, acknowledge_terms: bool, output_root: str):
    """Execute high-speed autonomous harvesting."""
    if acknowledge_terms:
        os.environ["PSE_TERMS_ACKNOWLEDGED"] = "1"

    # Parse years
    fy_list = []
    if "-" in years:
        p1, p2 = years.split("-")
        fy_list = list(range(int(p1), int(p2) + 1))
    elif "," in years:
        fy_list = [int(y.strip()) for y in years.split(",")]
    else:
        fy_list = [int(years.strip())]

    # Parse types
    type_list = [t.strip().upper() for t in types.split(",") if t.strip()]

    # Parse tickers
    tk_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else None

    settings = Settings(output_root=Path(output_root))
    pipeline = HarvestPipeline(settings)

    async def _exec():
        try:
            await pipeline.run(
                fiscal_years=fy_list,
                report_types=type_list,
                tickers=tk_list,
                max_issuers=max_issuers,
            )
        finally:
            await pipeline.close()

    asyncio.run(_exec())


@main.command()
@click.option("--acknowledge-terms", is_flag=True, help="Acknowledge PSE terms")
@click.option("--output-root", default="GLOBAL_SUSTAINABILITY_DATABASE", help="Target corpus directory")
def smoke(acknowledge_terms: bool, output_root: str):
    """Run smoke test on 10 benchmark issuers (FY2017-FY2025)."""
    if acknowledge_terms:
        os.environ["PSE_TERMS_ACKNOWLEDGED"] = "1"

    settings = Settings(output_root=Path(output_root))
    pipeline = HarvestPipeline(settings)

    async def _exec():
        try:
            await pipeline.run(
                fiscal_years=list(range(2017, 2026)),
                report_types=["AR", "SR"],
                tickers=BENCHMARK_SMOKE_TICKERS,
            )
        finally:
            await pipeline.close()

    asyncio.run(_exec())


if __name__ == "__main__":
    main()
