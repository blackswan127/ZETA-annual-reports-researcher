from __future__ import annotations

import re
from datetime import date

EXCLUDE = (
    "half year", "half-year", "interim", "quarterly", "appendix 4d",
    "appendix 4g", "corporate governance", "sustainability", "esg",
    "notice of annual general meeting", "notice of agm", "agm",
    "release and dispatch", "dispatch of", "supplementary information",
    "presentation", "results release", "results announcement",
)

STRONG = (
    "annual report and financial statements",
    "annual report and financial statement",
    "annual report to shareholders",
    "annual report for year ended",
    "appendix 4e and annual report",
    "annual report and accounts",
)


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()


def annual_score(title: str, pages: int | None = None) -> int:
    t = normalize_title(title).lower()
    if any(x in t for x in EXCLUDE):
        # Combined 4E + annual report is valid despite generic 4E wording.
        if "annual report" not in t:
            return -100
        if any(x in t for x in ("sustainability", "supplementary", "notice of", "release and dispatch", "agm")):
            return -100
    score = 0
    if any(x in t for x in STRONG):
        score += 100
    elif "annual report" in t:
        score += 85
    elif "annual financial report" in t:
        score += 80
    elif "full year financial report" in t or "full-year financial report" in t:
        score += 55
    elif re.search(r"\bfinancial report\b", t):
        score += 35
    else:
        return -100
    if "appendix 4e" in t and "annual report" in t:
        score += 10
    if pages is not None:
        if pages >= 40:
            score += 12
        elif pages >= 20:
            score += 5
        elif pages <= 5:
            score -= 35
    return score


def infer_fiscal_year(title: str, published: date) -> tuple[int, str]:
    t = normalize_title(title)
    # Explicit FY2025 / FY25.
    m = re.search(r"\bFY\s*[-_/]?\s*(20\d{2})\b", t, re.I)
    if m:
        return int(m.group(1)), "title_fy4"
    m = re.search(r"\bFY\s*[-_/]?\s*(\d{2})\b", t, re.I)
    if m:
        yy = int(m.group(1))
        return 2000 + yy, "title_fy2"
    # Prefer an explicit reporting-period phrase over unrelated years in a long title.
    m = re.search(r"year\s+ended.{0,60}?(20\d{2})", t, re.I)
    if m:
        return int(m.group(1)), "title_year_ended"
    m = re.search(r"\b(20\d{2})\s+annual\s+report\b", t, re.I)
    if m:
        return int(m.group(1)), "title_year_before_report"
    m = re.search(r"annual\s+report[^0-9]{0,30}(20\d{2})", t, re.I)
    if m:
        return int(m.group(1)), "title_year_after_report"
    # Prefer years near publication year; avoids grabbing unrelated historic years in a title.
    years = [int(x) for x in re.findall(r"\b(20\d{2})\b", t)]
    plausible = [y for y in years if published.year - 2 <= y <= published.year + 1]
    if plausible:
        return max(plausible), "title_year"
    # December-year companies commonly publish Jan-Apr in following calendar year.
    if published.month <= 5:
        return published.year - 1, "publication_heuristic_prev"
    return published.year, "publication_heuristic_same"
