import re

NEGATIVE = [
    "interim", "half year", "half-year", "quarter", "q1", "q2", "q3", "quarterly",
    "annual meeting", "agm", "egm", "notice of meeting", "proxy", "presentation",
    "sustainability report", "esg report", "brsr", "corporate governance", "annual return",
    "director report", "dividend", "price sensitive", "audit committee report"
]
POSITIVE = [
    "annual report", "annual report and financial statements", "annual financial report",
    "annual report & financial statements", "audited annual report"
]

def annual_report_score(title: str, body: str = "") -> float:
    t = f"{title} {body}".lower()
    if "annual return" in t: return -5.0
    if any(x in t for x in NEGATIVE) and "annual report" not in t: return -2.0
    score = 0.0
    if any(x in t for x in POSITIVE): score += 6
    if re.search(r"annual\s*report[_\-\s]*(?:20)?\d{2}", t): score += 2
    if "audited financial statements" in t and "annual" in t: score += 2
    if "annual report" in t and any(x in t for x in ["revised","amended","updated"]): score += .5
    return score

def is_annual_report(title: str, body: str = "") -> bool:
    return annual_report_score(title, body) >= 5

def infer_fiscal_year(title: str, body: str = "", publication_year: int | None = None):
    text = f"{title} {body}"
    # Bangladesh commonly labels reports 2024-25 / 2024-2025. Use the ending FY.
    m = re.search(r"\b(20(?:1[6-9]|2[0-5]))\s*[-/]\s*(20)?(\d{2})\b", text, re.I)
    if m:
        end = int(m.group(3)); return 2000 + end, "explicit-range"
    pats = [
        r"\bFY\s*(?:20)?(1[7-9]|2[0-5])\b",
        r"\byear ended[^0-9]{0,40}(20(?:1[7-9]|2[0-5]))\b",
        r"\bannual report\s*[-–:_ ]*\s*(20(?:1[7-9]|2[0-5]))\b",
        r"\b(20(?:1[7-9]|2[0-5]))\s+annual report\b",
    ]
    for p in pats:
        m=re.search(p,text,re.I)
        if m:
            raw=m.group(1); return (2000+int(raw) if len(raw)==2 else int(raw)),"explicit"
    years=[int(y) for y in re.findall(r"\b20(?:1[7-9]|2[0-5])\b", text)]
    if years: return max(years),"text-year"
    if publication_year: return publication_year,"publication-heuristic"
    return None,"unknown"
