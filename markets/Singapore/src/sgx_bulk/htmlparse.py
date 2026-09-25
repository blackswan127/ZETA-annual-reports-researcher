from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

SGX_LINKS_ORIGIN = "https://links.sgx.com"
ANNOUNCEMENT_RE = re.compile(r"^[A-Z0-9]{16}$")


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = next((v for k, v in attrs if k.casefold() == "href"), None)
        if href:
            self.links.append(href)


def announcement_id_from_url(url: str) -> str | None:
    path = urlparse(url).path.strip("/").split("/")
    try:
        idx = path.index("corporate-announcements")
    except ValueError:
        return None
    if idx + 1 >= len(path):
        return None
    ann = path[idx + 1].upper()
    return ann if ANNOUNCEMENT_RE.fullmatch(ann) else None


def safe_pdf_links(html: str, detail_url: str) -> list[tuple[str, str]]:
    ann = announcement_id_from_url(detail_url)
    if not ann:
        return []
    parser = LinkParser()
    parser.feed(html)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href in parser.links:
        url = urljoin(SGX_LINKS_ORIGIN, href.strip())
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.casefold() != "links.sgx.com":
            continue
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 4 or parts[:2] != ["1.0.0", "corporate-announcements"]:
            continue
        if parts[2].upper() != ann:
            continue
        filename = unquote(parts[-1])
        if not filename.casefold().endswith(".pdf"):
            continue
        if any(x in filename for x in ("/", "\\", "..")):
            continue
        if url not in seen:
            seen.add(url)
            out.append((url, filename))
    return out


def attachment_score(filename: str, fiscal_year: int | None = None) -> int:
    n = re.sub(r"[^a-z0-9]+", "", filename.casefold())
    score = 0
    if "annualreport" in n:
        score += 120
    elif re.search(r"(?:^|[^a-z])ar\s*20\d{2}", filename.casefold()):
        score += 90
    elif "annual" in n and "report" in n:
        score += 80
    if fiscal_year and str(fiscal_year) in filename:
        score += 20
    if "financialstatements" in n or "financialreport" in n:
        score += 15
    if "integratedreport" in n:
        score += 20
    reject = (
        "sustainability", "esg", "appendix", "circular", "proxy", "agm",
        "notice", "letter", "requestform", "informationstatement",
    )
    if any(term in n for term in reject):
        score -= 150
    return score
