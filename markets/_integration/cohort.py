from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from .contract import CohortManifest, CurrentIssuerRecord, resolve_market_info
from .promotion import build_sop_relative_path, is_valid_isin, is_valid_lei


def deduplicate_india_roster(records: List[CurrentIssuerRecord]) -> List[CurrentIssuerRecord]:
    """Deduplicate India BSE and NSE records by verified ISIN, retaining both exchange IDs."""
    by_isin: Dict[str, CurrentIssuerRecord] = {}
    without_isin: List[CurrentIssuerRecord] = []

    for r in records:
        clean_isin = r.isin.strip().upper()
        if is_valid_isin(clean_isin):
            if clean_isin in by_isin:
                existing = by_isin[clean_isin]
                # Merge exchange identifiers
                if existing.mic == "XNSE" and r.mic == "XBOM":
                    existing.secondary_mic = "XBOM"
                    existing.secondary_ticker = r.ticker
                elif existing.mic == "XBOM" and r.mic == "XNSE":
                    # Elevate NSE to primary
                    r.secondary_mic = "XBOM"
                    r.secondary_ticker = existing.ticker
                    by_isin[clean_isin] = r
            else:
                by_isin[clean_isin] = r
        else:
            without_isin.append(r)

    # Return sorted by ticker
    deduped = list(by_isin.values()) + without_isin
    deduped.sort(key=lambda x: (x.ticker, x.isin))
    return deduped


def check_issuer_completed_in_corpus(
    issuer: CurrentIssuerRecord,
    fiscal_years: List[int],
    corpus_root: Path,
    report_types: Optional[List[str]] = None,
) -> bool:
    """Check if all requested fiscal years and report types for this issuer already exist in GLOBAL_SUSTAINABILITY_DATABASE."""
    if not (is_valid_lei(issuer.lei) and is_valid_isin(issuer.isin)):
        return False

    r_types = report_types if report_types else ["AR"]

    for fy in fiscal_years:
        ir_rel = build_sop_relative_path(
            issuer.country_iso3,
            issuer.mic,
            issuer.lei,
            issuer.isin,
            issuer.ticker,
            fy,
            report_type="IR",
        )
        if (corpus_root / ir_rel).exists():
            continue  # IR combines financial and ESG narrative, fulfilling both slots

        for r_type in r_types:
            rel = build_sop_relative_path(
                issuer.country_iso3,
                issuer.mic,
                issuer.lei,
                issuer.isin,
                issuer.ticker,
                fy,
                report_type=r_type,
            )
            dest = corpus_root / rel
            if not dest.exists():
                return False
    return True


def select_exact_cohort(
    market: str,
    requested_count: int,
    fiscal_years: List[int],
    roster: List[CurrentIssuerRecord],
    corpus_root: Path,
    manifest_dir: Path,
    offset: int = 0,
    force_all: bool = False,
    report_types: Optional[List[str]] = None,
) -> CohortManifest:
    """Deterministically select exact-N active issuers for a run, excluding already completed ones."""
    info = resolve_market_info(market)
    canonical_market = info["name"]
    r_types = report_types if report_types else ["AR"]

    # Market-specific deduplication
    if canonical_market == "India":
        clean_roster = deduplicate_india_roster(roster)
    else:
        # Standard deduplication by ticker / issuer_id
        seen = set()
        clean_roster = []
        for r in roster:
            key = (r.ticker.strip().upper(), r.mic.strip().upper())
            if key not in seen:
                seen.add(key)
                clean_roster.append(r)
        clean_roster.sort(key=lambda x: x.ticker.strip().upper())

    # Filter out issuers already completed in corpus
    eligible: List[CurrentIssuerRecord] = []
    for issuer in clean_roster:
        if not force_all and corpus_root.exists() and check_issuer_completed_in_corpus(issuer, fiscal_years, corpus_root, report_types=r_types):
            continue
        eligible.append(issuer)

    # Deterministic slice
    selected = eligible[offset : offset + requested_count] if requested_count > 0 else eligible[offset:]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    type_tag = "_".join(r_types)
    run_id = f"{timestamp}_{canonical_market}_N{len(selected)}_{type_tag}"

    manifest = CohortManifest(
        run_id=run_id,
        market=canonical_market,
        country_iso3=info["iso3"],
        mic=info["mic"],
        requested_count=requested_count,
        selected_count=len(selected),
        fiscal_years=fiscal_years,
        issuers=selected,
        report_types=r_types,
    )

    # Freeze to JSON and CSV
    json_path = manifest_dir / f"{run_id}.json"
    csv_path = manifest_dir / f"{run_id}.csv"
    manifest.to_json(json_path)

    # Save CSV representation
    manifest_dir.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["issuer_id", "legal_name", "country_iso3", "mic", "ticker", "isin", "lei", "instrument_type", "secondary_mic", "secondary_ticker"])
        for i in selected:
            writer.writerow([i.issuer_id, i.legal_name, i.country_iso3, i.mic, i.ticker, i.isin, i.lei, i.instrument_type, i.secondary_mic, i.secondary_ticker])

    return manifest
