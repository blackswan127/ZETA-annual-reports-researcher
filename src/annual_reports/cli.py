"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .catalog import Report, load_manifest
from .discovery import (Company, DiscoveryStore, discover_sec_bulk, discover_sec_history, download_sec_bulk,
                        export_pdf_manifest, import_fca_csv, import_fca_historic_map,
                        parse_years, read_universe)
from .conversion import render_sec_html
from .fca_conversion import render_fca_originals
from .sustainability import import_metadata, ingest_zip
from .annualreports import import_annualreports
from .annualreports_site import (audit_reports as audit_annualreports_site,
                                 discover as discover_annualreports_site)
from .engine import RunLock, Settings, StateStore, native_path, run, verify_store


def _filter_cohort_pdfs(reports: list[Report], companies: list[Company]) -> list[Report]:
    """Keep direct-PDF reports whose complete listing identity is in the cohort."""
    company_identities = {
        (company.country, company.exchange, company.lei, company.isin, company.ticker)
        for company in companies
    }
    return [
        report for report in reports
        if (report.country, report.exchange, report.lei, report.isin, report.ticker)
        in company_identities
    ]


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="ar-harvest", description="US/UK SOP-compliant annual and sustainability PDF harvester")
    commands = cli.add_subparsers(dest="command", required=True)
    sr = commands.add_parser("sr-import", help="join authorized bulk/official sustainability metadata to any US/UK universe")
    sr.add_argument("universe", type=Path)
    sr.add_argument("metadata", type=Path)
    sr.add_argument("--direct", type=Path, default=Path("sr-direct.csv"))
    sr.add_argument("--bulk-index", type=Path, default=Path("sr-bulk-index.csv"))
    sr.add_argument("--review", type=Path, default=Path("sr-review.csv"))
    sr.add_argument("--years", default="2017:2025")
    sr_zip = commands.add_parser("sr-ingest-zip", help="validate and store authorized bulk ZIP PDFs under SOP names")
    sr_zip.add_argument("archive", type=Path)
    sr_zip.add_argument("--index", type=Path, default=Path("sr-bulk-index.csv"))
    sr_zip.add_argument("--output-root", type=Path, default=Path("GLOBAL_SUSTAINABILITY_DATABASE"))
    sr_zip.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    ars = commands.add_parser("annualreports-import", help="import authorized AnnualReports.com annual-report metadata")
    ars.add_argument("universe", type=Path)
    ars.add_argument("metadata", type=Path)
    ars.add_argument("--direct", type=Path, default=Path("annualreports-direct.csv"))
    ars.add_argument("--bulk-index", type=Path, default=Path("annualreports-bulk-index.csv"))
    ars.add_argument("--review", type=Path, default=Path("annualreports-review.csv"))
    ars.add_argument("--years", default="2017:2025")
    ars.add_argument("--authorized-hosted", action="store_true",
                     help="explicitly enable HostedData/Click direct URLs when your access permits automation")
    ars_zip = commands.add_parser("annualreports-ingest-zip", help="ingest an authorized AnnualReports.com bulk ZIP")
    ars_zip.add_argument("archive", type=Path)
    ars_zip.add_argument("--index", type=Path, default=Path("annualreports-bulk-index.csv"))
    ars_zip.add_argument("--output-root", type=Path, default=Path("GLOBAL_SUSTAINABILITY_DATABASE"))
    ars_zip.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    ars_site = commands.add_parser("annualreports-discover", help="resolve AnnualReports.com company-page PDF links")
    ars_site.add_argument("universe", type=Path)
    ars_site.add_argument("--manifest", type=Path, default=Path("annualreports-direct.csv"))
    ars_site.add_argument("--unresolved", type=Path, default=Path("annualreports-unresolved.csv"))
    ars_site.add_argument("--cache", type=Path, default=Path("cache/annualreports/pages"))
    ars_site.add_argument("--years", default="2017:2025")
    ars_site.add_argument("--refresh", action="store_true")
    ars_site.add_argument("--limit-companies", type=int)
    ars_audit = commands.add_parser("annualreports-audit", help="check downloaded PDFs for company and fiscal-year text")
    ars_audit.add_argument("universe", type=Path)
    ars_audit.add_argument("manifest", type=Path)
    ars_audit.add_argument("--output-root", type=Path, default=Path("GLOBAL_SUSTAINABILITY_DATABASE"))
    ars_audit.add_argument("--review", type=Path, default=Path("annualreports-content-review.csv"))
    plan = commands.add_parser("plan", help="validate a CSV manifest and show its download plan")
    plan.add_argument("manifest", type=Path)
    plan.add_argument("--allow-http", action="store_true", help="local testing only")
    universe = commands.add_parser("load-universe", help="load company identities and expected fiscal years")
    universe.add_argument("universe", type=Path)
    universe.add_argument("--years", default="2017:2025")
    universe.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    sec = commands.add_parser("discover-us", help="resolve SEC annual filing metadata from one bulk ZIP")
    sec.add_argument("--bulk-zip", type=Path, help="use a previously downloaded SEC submissions ZIP")
    sec.add_argument("--cache", type=Path, default=Path("cache/sec/submissions.zip"))
    sec.add_argument("--no-history", action="store_true", help="skip referenced historical submission JSON files")
    sec.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    fca = commands.add_parser("import-fca-csv", help="ingest the FCA NSM user-interface CSV export")
    fca.add_argument("csv_file", type=Path)
    fca.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    historic = commands.add_parser("import-fca-map", help="resolve old NSM links using FCA's migration ZIP")
    historic.add_argument("zip_file", type=Path)
    historic.add_argument("--all", action="store_true", help="store all 2017-2020 mappings; may be large")
    historic.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    export = commands.add_parser("export-manifest", help="write verified, direct-PDF candidates to CSV")
    export.add_argument("--output", type=Path, default=Path("resolved-reports.csv"))
    export.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    status = commands.add_parser("status", help="show universe and discovery coverage")
    status.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    benchmark = commands.add_parser("benchmark", help="live test on pending discovered direct PDFs")
    benchmark.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    benchmark.add_argument("--output-root", type=Path, default=Path("GLOBAL_SUSTAINABILITY_DATABASE"))
    benchmark.add_argument("--limit", type=int, default=200)
    benchmark.add_argument("--workers", type=int, default=32)
    benchmark.add_argument("--per-host", type=int, default=2)
    benchmark.add_argument("--allow-http", action="store_true", help="local testing only")
    benchmark.add_argument("--authorized-hosted", action="store_true")
    render = commands.add_parser("render-sec", help="download official SEC HTML and render local SOP PDFs")
    render.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    render.add_argument("--output-root", type=Path, default=Path("GLOBAL_SUSTAINABILITY_DATABASE"))
    render.add_argument("--cache", type=Path, default=Path("cache"))
    render.add_argument("--chrome", type=Path, help="Chrome/Chromium executable path")
    render.add_argument("--limit", type=int)
    render.add_argument("--network-workers", type=int, default=8)
    render.add_argument("--render-workers", type=int, default=4)
    render.add_argument("--browser-processes", type=int, default=1,
                        help="independent Chromium instances; total pages remain --render-workers")
    render.add_argument("--universe", type=Path, help="restrict rendering to companies in this universe CSV")
    fca_render = commands.add_parser("render-fca", help="preserve FCA originals and render XHTML/ZIP reports to SOP PDFs")
    fca_render.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    fca_render.add_argument("--output-root", type=Path, default=Path("GLOBAL_SUSTAINABILITY_DATABASE"))
    fca_render.add_argument("--cache", type=Path, default=Path("cache"))
    fca_render.add_argument("--chrome", type=Path)
    fca_render.add_argument("--limit", type=int)
    fca_render.add_argument("--network-workers", type=int, default=16)
    fca_render.add_argument("--render-workers", type=int, default=4)
    download = commands.add_parser("run", help="download, validate, hash and atomically store PDFs")
    download.add_argument("manifest", type=Path, nargs="?", help="CSV manifest; omit to use discovered PDF candidates")
    download.add_argument("--output-root", type=Path, default=Path("GLOBAL_SUSTAINABILITY_DATABASE"))
    download.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    download.add_argument("--workers", type=int, default=32)
    download.add_argument("--per-host", type=int, default=2)
    download.add_argument("--timeout", type=float, default=15.0)
    download.add_argument("--max-mib", type=int, default=64)
    download.add_argument("--attempts", type=int, default=2)
    download.add_argument("--allow-http", action="store_true", help="local testing only")
    download.add_argument("--replace", action="store_true", help="replace existing canonical files")
    download.add_argument("--authorized-hosted", action="store_true",
                          help="confirm your access permits automated AnnualReports.com PDF transfers")
    verify = commands.add_parser("verify", help="rehash and validate all recorded PDFs")
    verify.add_argument("--output-root", type=Path, default=Path("GLOBAL_SUSTAINABILITY_DATABASE"))
    verify.add_argument("--state", type=Path, default=Path("harvest.sqlite3"))
    batch = commands.add_parser("harvest-batch", help="run the full Two-Tier SEC EDGAR pipeline (discover, direct ARS PDFs, self-healing Chromium render, and verify)")
    batch.add_argument("universe", type=Path)
    batch.add_argument("--years", default="2017:2025")
    batch.add_argument("--state", type=Path, default=Path("local/harvest.sqlite3"))
    batch.add_argument("--output-root", type=Path, default=Path("GLOBAL_SUSTAINABILITY_DATABASE"))
    batch.add_argument("--cache", type=Path, default=Path("cache"))
    batch.add_argument("--workers", type=int, default=16)
    batch.add_argument("--per-host", type=int, default=8)
    batch.add_argument("--network-workers", type=int, default=8)
    batch.add_argument("--render-workers", type=int, default=6)
    batch.add_argument("--browser-processes", type=int, default=3)
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "annualreports-audit":
            summary = audit_annualreports_site(args.universe, args.manifest,
                                                args.output_root, args.review)
            print(json.dumps(summary, indent=2))
            return 1 if summary["review"] else 0
        if args.command == "annualreports-discover":
            years = parse_years(args.years)
            summary = asyncio.run(discover_annualreports_site(
                args.universe, args.manifest, args.unresolved, args.cache,
                years=(years[0], years[-1]), refresh=args.refresh,
                limit_companies=args.limit_companies))
            print(json.dumps(summary, indent=2))
            return 1 if summary["source_blocked"] else 0
        if args.command == "annualreports-import":
            years = parse_years(args.years)
            print(json.dumps(import_annualreports(args.universe, args.metadata, args.direct,
                                                  args.bulk_index, args.review,
                                                  authorized_hosted=args.authorized_hosted,
                                                  years=(years[0], years[-1])), indent=2))
            return 0
        if args.command == "annualreports-ingest-zip":
            summary = ingest_zip(args.archive, args.index, args.output_root, args.state)
            print(json.dumps(summary, indent=2))
            return 0 if not summary.get("failed") else 1
        if args.command == "sr-import":
            years = parse_years(args.years)
            print(json.dumps(import_metadata(args.universe, args.metadata, args.direct,
                                             args.bulk_index, args.review,
                                             (years[0], years[-1])), indent=2))
            return 0
        if args.command == "sr-ingest-zip":
            summary = ingest_zip(args.archive, args.index, args.output_root, args.state)
            print(json.dumps(summary, indent=2))
            return 0 if not summary.get("failed") else 1
        if args.command == "benchmark":
            if args.limit < 1:
                raise ValueError("limit must be positive")
            with RunLock(args.state):
                store = DiscoveryStore(args.state)
                try:
                    manifest = Path("resolved-reports.csv")
                    export_pdf_manifest(store, manifest)
                    candidates = load_manifest(manifest, allow_http=args.allow_http)
                    ledger = StateStore(args.state)
                    try:
                        pending = []
                        for report in candidates:
                            prior = ledger.prior(report)
                            target = native_path(args.output_root / report.relative_path)
                            complete = (prior and prior[0] == "downloaded" and
                                        prior[1] == report.pdf_url and os.path.isfile(target) and
                                        prior[2] == os.path.getsize(target))
                            if not complete:
                                pending.append(report)
                    finally:
                        ledger.close()
                finally:
                    store.close()
            selected = pending[:args.limit]
            if not selected:
                raise ValueError("no pending verified direct PDFs for benchmark")
            from rich.live import Live
            from rich.table import Table

            started = time.monotonic()
            metrics = {"attempts": 0, "downloaded": 0, "failed": 0}

            def table() -> Table:
                result = Table(title="Annual report benchmark")
                result.add_column("Metric")
                result.add_column("Value", justify="right")
                for name, value in (("Selected", len(selected)),
                                    ("Attempts", metrics["attempts"]),
                                    ("Downloaded", metrics["downloaded"]),
                                    ("Failed attempts", metrics["failed"]),
                                    ("Elapsed seconds", round(time.monotonic() - started, 1))):
                    result.add_row(name, str(value))
                return result

            settings = Settings(args.output_root, args.state, workers=args.workers,
                                per_host=args.per_host, allow_http=args.allow_http,
                                sec_user_agent=os.getenv("SEC_USER_AGENT", ""),
                                companies_house_key=os.getenv("COMPANIES_HOUSE_API_KEY", ""),
                                authorized_annualreports=args.authorized_hosted)
            with Live(table(), refresh_per_second=1) as live:
                def progress(attempts: int, _total: int, downloaded: int, failed: int) -> None:
                    metrics.update(attempts=attempts, downloaded=downloaded, failed=failed)
                    live.update(table())

                if os.name == "nt":
                    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                        summary = runner.run(run(selected, settings, progress=progress))
                else:
                    summary = asyncio.run(run(selected, settings, progress=progress))
            with RunLock(args.state):
                store = DiscoveryStore(args.state)
                try:
                    store.connection.execute(
                        """INSERT INTO benchmark_runs
                        (started_at, source, document_count, success_count, failed_count,
                         bytes, elapsed_s, documents_per_second)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (datetime.now(timezone.utc).isoformat(), "SEC_FCA_PDF",
                         summary["requested"], summary["downloaded"], summary["failed"],
                         summary["bytes"], summary["elapsed_s"], summary["pdfs_per_second"]),
                    )
                    store.commit()
                finally:
                    store.close()
            benchmark_row = {key: value for key, value in summary.items() if key != "failures"}
            benchmark_row["source"] = "SEC_FCA_PDF"
            benchmark_csv = Path("benchmark.csv")
            with benchmark_csv.open("a", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(benchmark_row))
                if stream.tell() == 0:
                    writer.writeheader()
                writer.writerow(benchmark_row)
            print(json.dumps(summary, indent=2))
            return 0 if summary["failed"] == 0 else 1
        if args.command in {"render-sec", "render-fca"}:
            chrome = args.chrome
            if chrome is None and os.name == "nt":
                for candidate in (Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
                                  Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")):
                    if candidate.is_file():
                        chrome = candidate
                        break
            if args.command == "render-sec":
                coroutine = render_sec_html(
                    args.state, args.output_root, args.cache,
                    os.getenv("SEC_USER_AGENT", ""), chrome_path=chrome,
                    limit=args.limit, network_workers=args.network_workers,
                    render_workers=args.render_workers,
                    browser_processes=args.browser_processes,
                    company_keys={c.key for c in read_universe(args.universe)} if args.universe else None,
                )
            else:
                coroutine = render_fca_originals(
                    args.state, args.output_root, args.cache,
                    chrome_path=chrome, limit=args.limit,
                    network_workers=args.network_workers,
                    render_workers=args.render_workers,
                )
            summary = asyncio.run(coroutine)
            print(json.dumps(summary, indent=2))
            return 0 if not summary["failed"] else 1
        if args.command in {"load-universe", "discover-us", "import-fca-csv", "import-fca-map", "export-manifest", "status"}:
            if args.command == "status" and not args.state.is_file():
                raise ValueError(f"state database not found: {args.state}")
            with RunLock(args.state):
                store = DiscoveryStore(args.state)
                try:
                    if args.command == "load-universe":
                        companies = read_universe(args.universe)
                        store.add_universe(companies, parse_years(args.years))
                        summary = store.status()
                    elif args.command == "discover-us":
                        archive = args.bulk_zip or download_sec_bulk(
                            args.cache, os.getenv("SEC_USER_AGENT", ""))
                        summary = discover_sec_bulk(store, archive)
                        if not args.no_history:
                            history = asyncio.run(discover_sec_history(
                                store, archive, args.cache.parent / "history",
                                os.getenv("SEC_USER_AGENT", "")))
                            summary["history"] = history
                    elif args.command == "import-fca-csv":
                        summary = import_fca_csv(store, args.csv_file)
                    elif args.command == "import-fca-map":
                        summary = import_fca_historic_map(store, args.zip_file,
                                                          import_all=args.all)
                    elif args.command == "export-manifest":
                        summary = export_pdf_manifest(store, args.output)
                    else:
                        summary = store.status()
                finally:
                    store.close()
            print(json.dumps(summary, indent=2))
            return 0
        if args.command == "plan":
            reports = load_manifest(args.manifest, allow_http=args.allow_http)
            summary = {
                "reports": len(reports),
                "countries": dict(Counter(r.country for r in reports)),
                "hosts": dict(Counter(urlsplit(r.pdf_url).hostname for r in reports)),
                "unverified": sum(not r.verified for r in reports),
            }
            print(json.dumps(summary, indent=2))
            return 0 if reports else 2
        if args.command == "run":
            manifest_path = args.manifest
            if manifest_path is None:
                with RunLock(args.state):
                    store = DiscoveryStore(args.state)
                    try:
                        exported = export_pdf_manifest(store, Path("resolved-reports.csv"))
                    finally:
                        store.close()
                if exported["pdf_rows"] == 0:
                    raise ValueError("no verified direct-PDF candidates; load a universe and discover/import sources first")
                manifest_path = Path("resolved-reports.csv")
            reports = load_manifest(manifest_path, allow_http=args.allow_http)
            settings = Settings(
                output_root=args.output_root, state_path=args.state,
                workers=args.workers, per_host=args.per_host, timeout_s=args.timeout,
                max_mib=args.max_mib, attempts=args.attempts, allow_http=args.allow_http,
                replace=args.replace, sec_user_agent=os.getenv("SEC_USER_AGENT", ""),
                companies_house_key=os.getenv("COMPANIES_HOUSE_API_KEY", ""),
                authorized_annualreports=args.authorized_hosted,
            )
            last_update = time.monotonic()

            def progress(attempts: int, total: int, downloaded: int, failed: int) -> None:
                nonlocal last_update
                now = time.monotonic()
                if attempts % 100 == 0 or now - last_update >= 10:
                    print(f"attempts={attempts} requested={total} downloaded={downloaded} failed_attempts={failed}", file=sys.stderr)
                    last_update = now

            if os.name == "nt":
                with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                    summary = runner.run(run(reports, settings, progress=progress))
            else:
                summary = asyncio.run(run(reports, settings, progress=progress))
            Path("run-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            with Path("failures.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=("path", "url", "error"))
                writer.writeheader()
                writer.writerows(summary["failures"])
            print(json.dumps(summary, indent=2))
            return 0 if summary["failed"] == 0 else 1
        if args.command == "harvest-batch":
            args.state.parent.mkdir(parents=True, exist_ok=True)
            args.output_root.mkdir(parents=True, exist_ok=True)
            companies = read_universe(args.universe)
            company_keys = {c.key for c in companies}
            years = parse_years(args.years)
            sec_agent = os.getenv("SEC_USER_AGENT", "blackswan capital khanholdings127@gmail.com")
            manifest_path = args.state.parent / f"{args.universe.stem}_pdf_manifest.csv"
            has_sec = any(bool(c.cik and c.cik.strip()) for c in companies)
            has_uk = any(c.country == "GBR" for c in companies)
            with RunLock(args.state):
                store = DiscoveryStore(args.state)
                try:
                    store.add_universe(companies, years)
                    if has_sec:
                        archive = download_sec_bulk(args.cache / "sec" / "submissions.zip", sec_agent)
                        discover_sec_bulk(store, archive)
                        asyncio.run(discover_sec_history(store, archive, args.cache / "sec" / "history", sec_agent))
                    if has_uk:
                        from .fca_catalog import build_or_open_fca_catalog, discover_fca_candidates
                        fca_map_zip = args.cache / "fca" / "mapping.zip"
                        if not fca_map_zip.is_file() and Path("cache/fca/mapping.zip").is_file():
                            fca_map_zip = Path("cache/fca/mapping.zip")
                        fca_conn = build_or_open_fca_catalog(args.cache / "fca", fca_map_zip)
                        discover_fca_candidates(store, fca_conn, company_keys)
                        fca_conn.close()
                    export_pdf_manifest(store, manifest_path)
                finally:
                    store.close()
            all_pdfs = load_manifest(manifest_path) if manifest_path.is_file() else []
            cohort_pdfs = _filter_cohort_pdfs(all_pdfs, companies)
            pdf_summary = {"downloaded": 0, "skipped": 0, "failed": 0}
            if cohort_pdfs:
                settings = Settings(
                    output_root=args.output_root, state_path=args.state,
                    workers=args.workers, per_host=args.per_host,
                    sec_user_agent=sec_agent,
                )
                if os.name == "nt":
                    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                        pdf_summary = runner.run(run(cohort_pdfs, settings))
                else:
                    pdf_summary = asyncio.run(run(cohort_pdfs, settings))
            chrome = None
            if os.name == "nt":
                for candidate in (Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
                                  Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")):
                    if candidate.is_file():
                        chrome = candidate
                        break
            render_summary = {"pdf_rendered": 0, "failed": 0}
            if has_sec:
                render_summary = asyncio.run(render_sec_html(
                    args.state, args.output_root, args.cache, sec_agent,
                    chrome_path=chrome, network_workers=args.network_workers,
                    render_workers=args.render_workers, browser_processes=args.browser_processes,
                    company_keys=company_keys,
                ))
            fca_render_summary = {"pdf_completed": 0, "failed": 0}
            if has_uk:
                fca_render_summary = asyncio.run(render_fca_originals(
                    args.state, args.output_root, args.cache,
                    chrome_path=chrome, network_workers=args.network_workers,
                    render_workers=args.render_workers,
                    company_keys=company_keys,
                ))
            verify_summary = verify_store(args.output_root, args.state)
            result = {
                "companies": len(companies),
                "direct_pdf": pdf_summary,
                "chromium_render": render_summary,
                "fca_render": fca_render_summary,
                "verify": verify_summary,
            }
            print(json.dumps(result, indent=2))
            return 0 if verify_summary.get("ok") else 1
        if not args.state.is_file():
            raise ValueError(f"state database not found: {args.state}")
        summary = verify_store(args.output_root, args.state)
        print(json.dumps(summary, indent=2))
        return 0 if summary["ok"] else 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
