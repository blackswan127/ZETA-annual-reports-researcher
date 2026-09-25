from __future__ import annotations

from dataclasses import dataclass
from datetime import date

@dataclass(slots=True)
class Issuer:
    issuer_key: str
    name: str
    ticker: str
    exchange_mic: str
    security_type: str = ""
    industry: str = ""
    listing_date: str = ""
    website: str = ""
    isin: str = ""
    lei: str = ""
    sedar_profile: str = ""
    active: bool = True
    eligible: bool = True
    source: str = ""

@dataclass(slots=True)
class Candidate:
    issuer_key: str
    fiscal_year: int
    title: str
    url: str
    source: str
    source_priority: int
    report_type: str = "AR"
    language: str = "EN"
    published_date: str = ""
    period_end: str = ""
    document_id: str = ""
    score: int = 0
    provenance: str = ""

@dataclass(slots=True)
class Validation:
    status: str
    bytes: int
    pages: int | None
    sha256: str
    semantic_status: str
    note: str = ""
