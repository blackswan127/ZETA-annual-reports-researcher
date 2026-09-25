from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True)
class Issuer:
    ibm_code: str
    stock_code: str
    issuer_name: str
    short_name: str
    market: str
    isin: str = ""

    @property
    def ticker(self) -> str:
        return "" if self.stock_code == self.ibm_code else f"{self.stock_code}.SI"


@dataclass(frozen=True)
class Filing:
    announcement_id: str
    ibm_code: str
    stock_code: str
    issuer_name: str
    short_name: str
    fiscal_year: int
    period_end: date
    broadcast_at: datetime
    detail_url: str
    title: str = "Annual Report"
    report_type: str = "AR"


@dataclass(frozen=True)
class Attachment:
    announcement_id: str
    url: str
    filename: str
    score: int


@dataclass(frozen=True)
class DownloadResult:
    attachment_url: str
    path: Path
    size_bytes: int
    sha256: str
    resumed: bool
