from __future__ import annotations

import re

NEGATIVE = (
    "annual return", "secretarial compliance", "secretarial audit", "business responsibility",
    "brsr", "sustainability report", "esg report", "corporate governance report", "newspaper",
    "scrutinizer", "voting result", "postal ballot", "notice of agm", "agm notice", "investor presentation",
    "transcript", "earnings call", "shareholding pattern", "financial results"
)
POSITIVE = (
    "annual report", "integrated annual report", "integrated report", "annual financial report"
)

def annual_report_score(title: str) -> int:
    t = " ".join((title or "").lower().split())
    if any(x in t for x in NEGATIVE):
        return -100
    score = 0
    if "annual report" in t:
        score += 100
    if "integrated annual report" in t or "integrated report" in t:
        score += 105
    if "reg. 34" in t or "regulation 34" in t:
        score += 25
    if "financial year" in t or "year ended" in t:
        score += 10
    if "revised" in t:
        score -= 10
    return score

def is_annual_report(title: str) -> bool:
    return annual_report_score(title) >= 90


def fiscal_year_from_text(text: str) -> int | None:
    s = text or ""
    # 2024-25 / 2024/25 / 2024–25 => FY end 2025
    m = re.search(r"\b(20\d{2})\s*[-/–]\s*(\d{2,4})\b", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b < 100:
            b = (a // 100) * 100 + b
            if b < a:
                b += 100
        if a <= b <= a + 1:
            return b
    # FY25 / FY2025
    m = re.search(r"\bFY\s*['-]?(20\d{2}|\d{2})\b", s, re.I)
    if m:
        n = int(m.group(1))
        return n if n >= 2000 else 2000 + n
    # year ended ... 2025
    m = re.search(r"\byear\s+ended.{0,45}?(20\d{2})\b", s, re.I)
    if m:
        return int(m.group(1))
    return None
