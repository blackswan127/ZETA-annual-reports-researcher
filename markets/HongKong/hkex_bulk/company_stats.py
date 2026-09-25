from __future__ import annotations

import calendar
import re
from datetime import date
from html.parser import HTMLParser

import httpx

BASE_URL = "https://www.hkex.com.hk/News/Market-Communications"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def parse_listed_company_count(html: str, as_of: date) -> dict[str, int] | None:
    """Extract HKEX's official Main Board/GEM company totals for one report date."""
    parser = _TextExtractor()
    parser.feed(html)
    text = " ".join(" ".join(parser.parts).split())
    if "Overview of listed companies" not in text or "Number of listed companies" not in text:
        return None

    date_text = f"{as_of.day} {as_of:%B %Y}"
    match = re.search(
        rf"As at\s+{re.escape(date_text)}\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)",
        text,
    )
    if not match:
        return None
    main_board, gem, total = (int(value.replace(",", "")) for value in match.groups())
    if main_board + gem != total:
        return None
    return {"main_board": main_board, "gem": gem, "total": total}


def _previous_month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _closed_months(today: date, count: int = 3):
    year, month = today.year, today.month
    if today.day < calendar.monthrange(year, month)[1]:
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    for _ in range(count):
        yield _previous_month_end(year, month)
        month -= 1
        if month == 0:
            year, month = year - 1, 12


async def fetch_official_listed_company_count(today: date | None = None) -> dict[str, object]:
    """Fetch the latest available official HKEX month-end company count."""
    today = today or date.today()
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for as_of in _closed_months(today):
            ymd = as_of.strftime("%y%m%d")
            for suffix in ("news", "2news", "3news"):
                url = f"{BASE_URL}/{as_of.year}/{ymd}{suffix}?sc_lang=en"
                try:
                    response = await client.get(url)
                except httpx.HTTPError:
                    continue
                if response.status_code != 200:
                    continue
                counts = parse_listed_company_count(response.text, as_of)
                if counts:
                    return {"as_of": as_of.isoformat(), **counts, "source_url": str(response.url)}
    raise RuntimeError("Could not find a recent official HKEX listed-company statistics report")
