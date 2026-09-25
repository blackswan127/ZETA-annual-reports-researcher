from dataclasses import dataclass
from typing import Optional

@dataclass
class Issuer:
    ticker: str
    name: str
    isin: str = ""
    lei: str = ""
    website: str = ""
    instrument_type: str = ""
    primary_listing_venue: str = ""
    fiscal_year_end: str = ""
    current: bool = True

@dataclass
class Candidate:
    ticker: str
    fiscal_year: int
    title: str
    url: str
    source: str
    publication_date: str = ""
    announcement_id: str = ""
    confidence: float = 0.0
    report_type: str = "AR"
    language: str = "EN"
