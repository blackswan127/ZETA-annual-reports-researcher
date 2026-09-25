from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .classifier import annual_score, classify_filing, infer_fiscal_year, normalize_title
from .models import Filing

BASE = "https://www.asx.com.au"

_META_RE = re.compile(r"\s+(\d+)\s+pages?\s+([\d.]+\s*(?:KB|MB|GB))\s*$", re.I)
_DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")


def parse_announcements_html(html: str, ticker: str, source_year: int) -> list[Filing]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Filing] = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        anchor = None
        for cell in reversed(cells):
            a = cell.find("a", href=True)
            if a and "displayAnnouncement.do" in a.get("href", ""):
                anchor = a
                break
        if anchor is None:
            continue
        date_text = cells[0].get_text(" ", strip=True)
        dm = _DATE_RE.search(date_text)
        if not dm:
            continue
        try:
            published = datetime.strptime(dm.group(1), "%d/%m/%Y").date()
        except ValueError:
            continue
        raw = normalize_title(anchor.get_text(" ", strip=True))
        pages = None
        size_text = ""
        mm = _META_RE.search(raw)
        if mm:
            pages = int(mm.group(1))
            size_text = mm.group(2).replace(" ", "")
            title = raw[: mm.start()].strip()
        else:
            title = raw
        href = urljoin(BASE, anchor["href"])
        qs = parse_qs(urlparse(href).query)
        announcement_id = (qs.get("idsId") or [""])[0]
        if not announcement_id:
            continue
        report_type, score = classify_filing(title, pages)
        if score < 0 or not report_type:
            continue
        fy, method = infer_fiscal_year(title, published)
        out.append(
            Filing(
                ticker=ticker.upper(),
                published_date=published,
                title=title,
                display_url=href,
                announcement_id=announcement_id,
                pages=pages,
                size_text=size_text,
                source_year=source_year,
                fiscal_year=fy,
                year_method=method,
                score=score,
                report_type=report_type,
            )
        )
    return out


def parse_pdf_url(html: str, base_url: str = BASE) -> str:
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", attrs={"name": "pdfURL"})
    if inp and inp.get("value"):
        return urljoin(base_url, str(inp["value"]))
    # Some variants expose the asxpdf URL as a regular link.
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if "/asxpdf/" in href and href.lower().endswith(".pdf"):
            return urljoin(base_url, href)
    return ""
