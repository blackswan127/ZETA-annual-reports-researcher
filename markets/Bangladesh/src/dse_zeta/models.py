from dataclasses import dataclass

@dataclass
class Issuer:
    ticker: str
    name: str
    isin: str = ""
    lei: str = ""
    website: str = ""
    financials_url: str = ""
    instrument_type: str = ""
    board: str = ""
    category: str = ""
    sector: str = ""
    fiscal_year_end: str = ""
    operational_status: str = ""
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
