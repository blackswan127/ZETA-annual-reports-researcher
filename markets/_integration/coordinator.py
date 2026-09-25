from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .adapters import get_market_adapter
from .cohort import select_exact_cohort
from .contract import CohortManifest, CurrentIssuerRecord, SlotResult, resolve_market_info

DEFAULT_CORPUS_ROOT = Path("GLOBAL_SUSTAINABILITY_DATABASE")


@dataclass
class RunSummary:
    run_id: str
    market: str
    directive: str
    requested_issuers: int
    selected_current_issuers: int
    issuer_year_slots: int
    verified_pdfs: int
    promoted_pdfs: int
    staged_unresolved_identity: int
    failed_slots: int
    unresolved_slots: int
    elapsed_seconds: float
    throughput_docs_per_sec: float
    throughput_mbs: float
    roster_timestamp: str
    output_directory: str
    manifest_path: str
    slot_results: List[SlotResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["slot_results"] = [r.to_dict() for r in self.slot_results]
        return d

    def print_summary(self) -> None:
        print("\n" + "=" * 70)
        print(f"HARVEST EXECUTION AUDIT: {self.market} (Run ID: {self.run_id})")
        print("=" * 70)
        print(f"Directive:                 {self.directive}")
        print(f"Requested Issuers:         {self.requested_issuers}")
        print(f"Selected Current Issuers:  {self.selected_current_issuers}")
        print(f"Issuer-Year Slots:         {self.issuer_year_slots}")
        print(f"Verified PDFs:             {self.verified_pdfs}")
        print(f"Promoted to SOP Corpus:    {self.promoted_pdfs}")
        print(f"Staged (Missing Identity): {self.staged_unresolved_identity}")
        print(f"Failed Slots:              {self.failed_slots}")
        print(f"Unresolved Slots:          {self.unresolved_slots}")
        print(f"Elapsed Time:              {self.elapsed_seconds:.2f}s")
        print(f"Doc Throughput:            {self.throughput_docs_per_sec:.2f} docs/sec")
        print(f"Network Throughput:        {self.throughput_mbs:.2f} MB/s")
        print(f"Roster Snapshot As-Of:     {self.roster_timestamp}")
        print(f"Final Output Corpus:       {self.output_directory}")
        print(f"Frozen Cohort Manifest:    {self.manifest_path}")
        print("=" * 70 + "\n")


def parse_plain_english_directive(prompt: str) -> Dict[str, Any]:
    """Parse plain-English instructions into market, count, and fiscal years."""
    p_lower = prompt.lower()

    # 1. Market detection
    market = None
    market_keywords = {
        "Australia": ["australia", "asx", "aussie"],
        "Bangladesh": ["bangladesh", "dhaka", "dse"],
        "Canada": ["canada", "tsx", "tsxv", "canadian"],
        "HongKong": ["hong kong", "hongkong", "hkex", "sehk"],
        "India": ["india", "bse", "nse", "indian"],
        "NewZealand": ["new zealand", "newzealand", "nzx", "kiwi"],
        "Singapore": ["singapore", "sgx"],
        "SriLanka": ["sri lanka", "srilanka", "cse", "colombo"],
        "Africa": [
            "africa", "african", "jse", "south africa", "ngx", "nigeria", "kenya", "nse kenya",
            "ghana", "gse", "botswana", "bse", "zambia", "luse", "tanzania", "dse tanzania",
            "zimbabwe", "mauritius", "namibia", "uganda", "malawi", "rwanda", "eswatini", "seychelles", "sierra leone",
        ],
    }
    for m, kw_list in market_keywords.items():
        if any(kw in p_lower for kw in kw_list):
            market = m
            break
    if not market:
        raise ValueError(f"Could not identify target market from directive: '{prompt}'")

    # 2. Count detection (e.g., "next 100", "50 companies", "10 issuers", "all currently listed companies")
    count = 100  # Default cohort size
    if "all" in p_lower and ("company" in p_lower or "companies" in p_lower or "listed" in p_lower or "issuer" in p_lower):
        count = 999999
    else:
        m_count = re.search(r"\b(?:next\s+|first\s+|top\s+)?(\d+)\s*(?:companies|issuers|stocks|corporations|firms|entities)?\b", p_lower)
        if m_count:
            try:
                val = int(m_count.group(1))
                if 1 <= val <= 10000:
                    count = val
            except Exception:
                pass

    # 3. Fiscal Year detection
    # Examples: "FY2024", "2024", "2017-2025", "FY17-FY25"
    fiscal_years = []
    # Range check
    m_range = re.search(r"(?:fy)?(20\d\d)\s*(?:-|to)\s*(?:fy)?(20\d\d)", p_lower)
    if m_range:
        y1, y2 = int(m_range.group(1)), int(m_range.group(2))
        fiscal_years = list(range(min(y1, y2), max(y1, y2) + 1))
    else:
        # Single years (handles 2024, FY2024, fy 2024)
        years = [int(y) for y in re.findall(r"(?:^|[^0-9a-z])(?:fy\s*)?(20[12]\d)(?:$|[^0-9a-z])", p_lower)]
        if years:
            fiscal_years = sorted(list(set(years)))
        else:
            # Default to FY2024 if unstated, or full range if requested
            if "all" in p_lower or "2017" in p_lower:
                fiscal_years = list(range(2017, 2026))
            else:
                fiscal_years = [2024]

    offset = 0
    if "next" in p_lower:
        # Will be calculated dynamically based on completed issuers
        offset = -1  # Flag for auto-offset

    return {
        "market": market,
        "count": count,
        "fiscal_years": fiscal_years,
        "offset": offset,
    }


class Coordinator:
    def __init__(self, corpus_root: Path = DEFAULT_CORPUS_ROOT):
        self.corpus_root = corpus_root.resolve()

    async def execute_directive(
        self,
        prompt: str,
        custom_corpus: Optional[Path] = None,
        force_offset: Optional[int] = None,
    ) -> RunSummary:
        t0 = time.time()
        parsed = parse_plain_english_directive(prompt)
        market_name = parsed["market"]
        count = parsed["count"]
        fiscal_years = parsed["fiscal_years"]
        target_corpus = custom_corpus or self.corpus_root

        adapter = get_market_adapter(market_name)
        print(f"[{market_name}] Loading active issuer roster from official sources...")
        roster = await adapter.load_roster(refresh=False)
        print(f"[{market_name}] Total current active roster: {len(roster)} issuers")

        # Determine offset if 'next' was requested
        offset = force_offset if force_offset is not None else 0
        if parsed["offset"] == -1 and force_offset is None:
            # Auto-skip completed issuers
            offset = 0  # select_exact_cohort automatically skips completed issuers in target corpus

        print(f"[{market_name}] Selecting exact cohort of {count} issuers for {fiscal_years}...")
        cohort = select_exact_cohort(
            market=market_name,
            requested_count=count,
            fiscal_years=fiscal_years,
            roster=roster,
            corpus_root=target_corpus,
            manifest_dir=adapter.manifest_dir,
            offset=offset,
        )
        print(f"[{market_name}] Frozen cohort manifest: {len(cohort.issuers)} issuers staged in run {cohort.run_id}")

        manifest_file = adapter.manifest_dir / f"{cohort.run_id}.json"

        # Execute autonomous harvesting
        print(f"[{market_name}] Initiating harvesting and SOP promotion to {target_corpus}...")
        results = await adapter.harvest_cohort(cohort, target_corpus)

        elapsed = time.time() - t0
        total_bytes = sum(r.file_size_bytes for r in results)
        promoted = sum(1 for r in results if r.status in ("PROMOTED", "IDEMPOTENT_EXISTING"))
        staged = sum(1 for r in results if r.status == "STAGED_UNRESOLVED_IDENTITY")
        verified = sum(1 for r in results if r.page_count > 0 and r.sha256)
        failed = sum(1 for r in results if r.status == "FAILED")
        unresolved = sum(1 for r in results if r.status == "UNRESOLVED")

        doc_tput = len(results) / elapsed if elapsed > 0 else 0.0
        mb_tput = (total_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0.0

        summary = RunSummary(
            run_id=cohort.run_id,
            market=market_name,
            directive=prompt,
            requested_issuers=count,
            selected_current_issuers=len(cohort.issuers),
            issuer_year_slots=len(cohort.issuers) * len(fiscal_years),
            verified_pdfs=verified,
            promoted_pdfs=promoted,
            staged_unresolved_identity=staged,
            failed_slots=failed,
            unresolved_slots=unresolved,
            elapsed_seconds=round(elapsed, 2),
            throughput_docs_per_sec=round(doc_tput, 2),
            throughput_mbs=round(mb_tput, 2),
            roster_timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            output_directory=str(target_corpus),
            manifest_path=str(manifest_file),
            slot_results=results,
        )

        # Save summary JSON
        summary_path = adapter.manifest_dir / f"{cohort.run_id}_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=2)

        summary.print_summary()
        return summary
