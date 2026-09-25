from __future__ import annotations

from dataclasses import dataclass
from datetime import date

@dataclass(slots=True)
class Issuer:
    ticker: str
    name: str
    industry: str = ""
    listing_date: str = ""
    source: str = ""

@dataclass(slots=True)
class Filing:
    ticker: str
    published_date: date
    title: str
    display_url: str
    announcement_id: str
    pages: int | None = None
    size_text: str = ""
    source_year: int | None = None
    fiscal_year: int | None = None
    year_method: str = ""
    score: int = 0
    pdf_url: str = ""
