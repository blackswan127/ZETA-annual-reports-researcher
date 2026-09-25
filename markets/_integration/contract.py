from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Canonical country ISO3 to default MIC mapping
MARKET_DEFAULTS = {
    "Australia": {"iso3": "AUS", "mic": "XASX", "aliases": ["ASX", "AUS", "AUSTRALIA"]},
    "Bangladesh": {"iso3": "BGD", "mic": "XDHA", "aliases": ["DSE", "DHAKA", "BGD", "BANGLADESH"]},
    "Canada": {"iso3": "CAN", "mic": "XTSE", "secondary_mics": ["XTSX"], "aliases": ["TSX", "TSXV", "CAN", "CANADA"]},
    "HongKong": {"iso3": "HKG", "mic": "XHKG", "aliases": ["HKEX", "HKG", "HONGKONG", "HONG KONG"]},
    "India": {"iso3": "IND", "mic": "XNSE", "secondary_mics": ["XBOM"], "aliases": ["BSE", "NSE", "IND", "INDIA"]},
    "NewZealand": {"iso3": "NZL", "mic": "XNZE", "aliases": ["NZX", "NZL", "NEWZEALAND", "NEW ZEALAND"]},
    "Singapore": {"iso3": "SGP", "mic": "XSES", "aliases": ["SGX", "SGP", "SINGAPORE"]},
}


def resolve_market_info(market_name: str) -> Dict[str, Any]:
    norm = market_name.strip().upper().replace(" ", "")
    for canonical, info in MARKET_DEFAULTS.items():
        if canonical.upper() == norm:
            return {"name": canonical, **info}
        for alias in info["aliases"]:
            if alias.upper().replace(" ", "") == norm:
                return {"name": canonical, **info}
    raise ValueError(f"Unknown market '{market_name}'. Supported markets: {list(MARKET_DEFAULTS.keys())}")


@dataclass
class CurrentIssuerRecord:
    """Current active listed issuer record."""
    issuer_id: str
    legal_name: str
    country_iso3: str
    mic: str
    ticker: str
    isin: str = ""
    lei: str = ""
    instrument_type: str = "Equity"
    active_status: str = "ACTIVE"
    as_of_date: str = ""
    source_url: str = ""
    secondary_mic: str = ""
    secondary_ticker: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["extra"] = json.dumps(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CurrentIssuerRecord:
        data = dict(data)
        if "extra" in data and isinstance(data["extra"], str) and data["extra"]:
            try:
                data["extra"] = json.loads(data["extra"])
            except Exception:
                data["extra"] = {}
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class RequestedSlot:
    """A requested annual report filing slot."""
    run_id: str
    issuer_id: str
    fiscal_year: int
    report_type: str = "AR"
    language: str = "EN"
    country_iso3: str = ""
    mic: str = ""
    ticker: str = ""
    isin: str = ""
    lei: str = ""

    def slot_key(self) -> str:
        return f"{self.issuer_id}:FY{self.fiscal_year}:{self.report_type}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RequestedSlot:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CandidateFiling:
    """Discovered candidate filing for an issuer and fiscal year."""
    candidate_id: str
    issuer_id: str
    fiscal_year: int
    publication_date: str
    filing_title: str
    source_type: str
    source_url: str
    confidence_score: float = 1.0
    is_split_part: bool = False
    part_number: int = 1
    total_parts: int = 1
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["extra"] = json.dumps(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CandidateFiling:
        data = dict(data)
        if "extra" in data and isinstance(data["extra"], str) and data["extra"]:
            try:
                data["extra"] = json.loads(data["extra"])
            except Exception:
                data["extra"] = {}
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SlotResult:
    """Final auditable outcome of an issuer-year report slot."""
    slot_id: str
    run_id: str
    issuer_id: str
    fiscal_year: int
    status: str  # PROMOTED, VERIFIED, STAGED_UNRESOLVED_IDENTITY, FAILED, UNRESOLVED, CONFLICT
    reason: str = ""
    sha256: str = ""
    page_count: int = 0
    file_size_bytes: int = 0
    destination_path: str = ""
    source_url: str = ""
    elapsed_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SlotResult:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CohortManifest:
    """Frozen run manifest governing an exact-N execution."""
    run_id: str
    market: str
    country_iso3: str
    mic: str
    requested_count: int
    selected_count: int
    fiscal_years: List[int]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    issuers: List[CurrentIssuerRecord] = field(default_factory=list)

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": self.run_id,
            "market": self.market,
            "country_iso3": self.country_iso3,
            "mic": self.mic,
            "requested_count": self.requested_count,
            "selected_count": self.selected_count,
            "fiscal_years": self.fiscal_years,
            "created_at": self.created_at,
            "issuers": [i.to_dict() for i in self.issuers],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    @classmethod
    def from_json(cls, path: Path) -> CohortManifest:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        issuers = [CurrentIssuerRecord.from_dict(i) for i in data.get("issuers", [])]
        return cls(
            run_id=data["run_id"],
            market=data["market"],
            country_iso3=data["country_iso3"],
            mic=data["mic"],
            requested_count=data["requested_count"],
            selected_count=data["selected_count"],
            fiscal_years=data["fiscal_years"],
            created_at=data.get("created_at", ""),
            issuers=issuers,
        )
