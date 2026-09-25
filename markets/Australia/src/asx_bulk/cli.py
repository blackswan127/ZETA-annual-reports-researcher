from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .config import Settings
from .pipeline import Pipeline


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="asx-bulk", description="ASX current-listed annual report bulk downloader")
    p.add_argument("--output", default="output")
    p.add_argument("--start-year", type=int, default=2017)
    p.add_argument("--end-year", type=int, default=2025)
    p.add_argument("--metadata-workers", type=int, default=10)
    p.add_argument("--metadata-rps", type=float, default=3.0)
    p.add_argument("--download-workers", type=int, default=6)
    p.add_argument("--download-rps", type=float, default=3.0)
    p.add_argument("--retries", type=int, default=5)
    p.add_argument("--shard-count", type=int, default=1, help="deterministically split tickers across N workers/machines")
    p.add_argument("--shard-index", type=int, default=0, help="this shard index, 0..N-1")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("universe")
    d = sub.add_parser("discover")
    d.add_argument("--ticker", action="append", default=[])
    d.add_argument("--force", action="store_true")
    dl = sub.add_parser("download")
    dl.add_argument("--limit", type=int)
    dl.add_argument("--ticker", action="append", default=[])
    sub.add_parser("audit")
    s = sub.add_parser("smoke")
    s.add_argument("--ticker", default="BHP")
    s.add_argument("--year", type=int, default=2025)
    sub.add_parser("run")
    return p


def main() -> None:
    args = parser().parse_args()
    s = Settings(
        output_dir=Path(args.output), start_year=args.start_year, end_year=args.end_year,
        metadata_workers=args.metadata_workers, metadata_rps=args.metadata_rps,
        download_workers=args.download_workers, download_rps=args.download_rps,
        retries=args.retries, shard_count=max(1,args.shard_count), shard_index=max(0,args.shard_index),
    )
    if s.shard_index >= s.shard_count:
        raise SystemExit("--shard-index must be smaller than --shard-count")
    pipe = Pipeline(s)
    try:
        if args.cmd == "universe":
            print(asyncio.run(pipe.refresh_universe()))
        elif args.cmd == "discover":
            asyncio.run(pipe.discover(args.ticker or None, args.force))
        elif args.cmd == "download":
            asyncio.run(pipe.download(args.limit, args.ticker or None))
        elif args.cmd == "audit":
            pipe.audit()
        elif args.cmd == "smoke":
            asyncio.run(pipe.smoke(args.ticker, args.year))
        elif args.cmd == "run":
            asyncio.run(pipe.run_all())
    finally:
        pipe.close()

if __name__ == "__main__":
    main()
