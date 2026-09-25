from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class Issuer:
    issuer_id: str
    iso3: str
    mic: str
    ticker: str
    company_name: str
    isin: str = ""
    lei: str = ""
    fiscal_year_end: str = ""
    active: int = 1
    universe_source: str = ""
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
    required_class: str = "AR_FULL"
    status: str = "PENDING"  # PENDING, DISCOVERING, AR_FULL_FOUND, ANNUAL_COMPONENT_FOUND, READY, DOWNLOADING, DONE, MISSING_AR_FULL, FAILED, SOURCE_BLOCKED, IDENTITY_MISSING, LANGUAGE_REVIEW, FY_REVIEW
    selected_candidate_id: Optional[str] = None

    def slot_key(self) -> str:
        return f"{self.issuer_id}:FY{self.fiscal_year}:{self.required_class}"


@dataclass
class Candidate:
    candidate_id: str
    issuer_id: str
    source_name: str
    source_url: str
    title: str
    direct_url: Optional[str] = None
    publication_date: str = ""
    period_end: str = ""
    resolved_fy: Optional[int] = None
    fy_confidence: float = 0.0
    language: str = "EN"
    language_confidence: float = 1.0
    document_class: str = "AR_FULL"  # AR_FULL, ANNUAL_FS_COMPONENT, GOVERNANCE_COMPONENT, ESG_COMPONENT, REJECT
    class_confidence: float = 0.0
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DownloadRecord:
    candidate_id: str
    state: str  # DONE, FAILED, IDENTITY_MISSING, RETRY
    attempts: int = 0
    bytes_downloaded: int = 0
    http_status: Optional[int] = None
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
    health: str = "UNKNOWN"
    consecutive_failures: int = 0
    terms_reviewed: int = 0
    last_success: Optional[str] = None
    last_failure: Optional[str] = None


@dataclass
class Event:
    event_type: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    issuer_id: Optional[str] = None
    fiscal_year: Optional[int] = None
    details: str = ""
