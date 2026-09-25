from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class Issuer:
    issuer_id: str
    country_iso3: str
    exchange_mic: str
    ticker: str
    company_name: str
    isin: str = ""
    lei: str = ""
    fiscal_year_end: str = ""
    active: int = 1
    source_url: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Issuer:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ExpectedSlot:
    issuer_id: str
    fiscal_year: int
    report_type: str = "AR"
    status: str = "PENDING"  # PENDING, DISCOVERING, CANDIDATE_FOUND, FY_REVIEW, READY, DOWNLOADING, DONE, MISSING, FAILED, SOURCE_BLOCKED, IDENTITY_MISSING, REVIEW

    def slot_key(self) -> str:
        return f"{self.issuer_id}:FY{self.fiscal_year}:{self.report_type}"


@dataclass
class Candidate:
    candidate_id: str
    issuer_id: str
    source_name: str
    source_url: str
    title: str
    publication_date: str = ""
    resolved_fy: Optional[int] = None
    fy_confidence: float = 0.0
    classification: str = "AR"  # AR, ESG, OTHER, REVIEW
    classification_score: float = 0.0
    direct_pdf_url: str = ""
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DownloadRecord:
    candidate_id: str
    state: str  # DOWNLOADING, DONE, FAILED, IDENTITY_MISSING
    attempts: int = 0
    bytes_downloaded: int = 0
    http_status: Optional[int] = None
    content_type: str = ""
    sha256: str = ""
    local_path: str = ""
    error: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SourceProfile:
    source_key: str
    host: str
    adapter: str
    requests_per_second: float = 1.0
    max_concurrency: int = 2
    health: str = "UNKNOWN"  # UNKNOWN, HEALTHY, DEGRADED, BLOCKED
    last_success: str = ""
    last_failure: str = ""
    consecutive_failures: int = 0
    terms_reviewed: int = 0


@dataclass
class Event:
    id: Optional[int] = None
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    issuer_id: Optional[str] = None
    fiscal_year: Optional[int] = None
    event_type: str = ""
    details: str = ""
