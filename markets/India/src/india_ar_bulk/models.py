from __future__ import annotations

from dataclasses import dataclass

@dataclass(slots=True)
class Issuer:
    issuer_key: str
    isin: str
    name: str
    nse_symbol: str = ""
    nse_series: str = ""
    nse_sme: bool = False
    bse_scrip: str = ""
    bse_group: str = ""
    source_flags: str = ""

@dataclass(slots=True)
class Candidate:
    issuer_key: str
    fiscal_year: int
    source: str
    source_id: str
    title: str
    url: str
    published_at: str = ""
    from_year: int | None = None
    to_year: int | None = None
    file_kind: str = "PDF"
    score: int = 0
    selected: bool = False
    note: str = ""
