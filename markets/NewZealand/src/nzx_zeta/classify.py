import re

NEGATIVE = [
    "interim", "half year", "half-year", "quarter", "annual meeting", "agm", "notice of meeting",
    "presentation", "investor presentation", "sustainability report", "climate statement", "climate report",
    "esg report", "corporate governance statement", "annual return", "distribution notice", "results announcement"
]
POSITIVE = ["annual report", "annual financial report", "annual report and financial statements", "statutory annual report"]

def annual_report_score(title: str, announcement_type: str = "", body: str = "") -> float:
    t = f"{title} {body}".lower()
    if any(x in t for x in NEGATIVE) and not "annual report" in t:
        return -1.0
    score = 0.0
    if announcement_type.upper() == "ANNREP": score += 5
    if any(x in t for x in POSITIVE): score += 5
    if "audited financial statements" in t: score += 1
    if "annual shareholder review" in t and "annual report" not in t: score -= 2
    if "updated" in t or "amended" in t: score += 0.5
    return score

def is_annual_report(title: str, announcement_type: str = "", body: str = "") -> bool:
    return annual_report_score(title, announcement_type, body) >= 5

def infer_fiscal_year(title: str, body: str = "", publication_year: int | None = None) -> tuple[int | None, str]:
    text = f"{title} {body}"
    patterns = [
        r"\bFY\s*(?:20)?(1[7-9]|2[0-5])\b",
        r"\bfinancial year(?: ended)?[^0-9]{0,20}(20(?:1[7-9]|2[0-5]))\b",
        r"\byear ended[^0-9]{0,40}(20(?:1[7-9]|2[0-5]))\b",
        r"\bannual report\s*[-–:]?\s*(20(?:1[7-9]|2[0-5]))\b",
        r"\b(20(?:1[7-9]|2[0-5]))\s+annual report\b",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.I)
        if m:
            raw = m.group(1)
            if len(raw) == 2: return 2000 + int(raw), "explicit"
            return int(raw), "explicit"
    years = [int(y) for y in re.findall(r"\b20(?:1[7-9]|2[0-5])\b", text)]
    if years:
        return max(years), "text-year"
    if publication_year:
        return publication_year, "publication-heuristic"
    return None, "unknown"
