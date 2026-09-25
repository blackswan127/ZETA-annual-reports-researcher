from __future__ import annotations

import re
from datetime import datetime

NEGATIVE = [
    r"annual return", r"annual information form", r"management information circular", r"proxy",
    r"notice of meeting", r"agm", r"sustainab", r"esg", r"climate", r"quarter", r"interim",
    r"financial statements only", r"md&a", r"management discussion", r"presentation", r"news release",
]
POSITIVE = [
    r"annual report", r"annual report to shareholders", r"annual financial report", r"year in review",
    r"report to shareholders", r"integrated annual report",
]


def classify_title(title: str, url: str = "") -> tuple[bool, int]:
    text = f"{title} {url}".lower()
    if any(re.search(p, text) for p in NEGATIVE):
        return False, -100
    score = 0
    if re.search(r"\bannual report\b", text): score += 80
    if re.search(r"\breport to shareholders\b", text): score += 55
    if re.search(r"\bintegrated annual report\b", text): score += 60
    if re.search(r"\bannual\b", text): score += 15
    if url.lower().endswith(".pdf"): score += 10
    return score >= 30, score


def infer_fiscal_year(title: str = "", period_end: str = "", published_date: str = "", url: str = "") -> tuple[int | None, str]:
    for raw in (period_end,):
        if raw:
            years = re.findall(r"(?:19|20)\d{2}", raw)
            if years:
                return int(years[-1]), "period_end"
    text = " ".join([title, url])
    patterns = [
        r"(?:FY|FISCAL\s+YEAR|YEAR\s+ENDED|YEAR\s+ENDING)\s*[-:/ ]*?(20\d{2})",
        r"\b(20\d{2})\s+(?:ANNUAL\s+REPORT|REPORT\s+TO\s+SHAREHOLDERS)\b",
        r"\b(?:ANNUAL\s+REPORT|REPORT\s+TO\s+SHAREHOLDERS)\s*[-:/ ]*?(20\d{2})\b",
    ]
    up = text.upper()
    for p in patterns:
        m = re.search(p, up)
        if m:
            return int(m.group(1)), "title"
    if published_date:
        m = re.search(r"(20\d{2})", published_date)
        if m:
            y = int(m.group(1))
            # Canadian annual reports are commonly published in the following calendar year.
            return y - 1, "publication_heuristic_minus1"
    return None, "unknown"


def detect_language(title: str = "", url: str = "", declared: str = "") -> str:
    d = (declared or "").strip().upper()
    if d in {"EN", "ENG", "ENGLISH"}: return "EN"
    if d in {"FR", "FRE", "FRA", "FRENCH", "FRANCAIS", "FRANÇAIS"}: return "FR"
    text = f"{title} {url}".lower()
    if re.search(r"rapport annuel|français|francais|_fr\b|-fr\b", text): return "FR"
    return "EN"
