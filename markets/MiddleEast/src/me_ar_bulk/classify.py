from __future__ import annotations

import re
from typing import Tuple

# Exclusion patterns for interim, governance, notices, summaries
INTERIM_PATTERNS = [
    r"\b(?:half[-\s]?year|semi[-\s]?annual|hy\b|h1\b|h2\b)",
    r"\b(?:first|second|third|fourth)\s+quarter",
    r"\b(?:1st|2nd|3rd|4th)\s+quarter",
    r"\b(?:q1|q2|q3|q4)\b",
    r"\binterim\b",
    r"\bquarterly\b",
]

GOVERNANCE_PATTERNS = [
    r"\bcorporate\s+governance\s+report\b",
    r"\bgovernance\s+report\b",
    r"\bboard\s+of\s+directors\s+report\b",
]

ESG_PATTERNS = [
    r"\bsustainability\s+report\b",
    r"\besg\s+report\b",
    r"\bcsr\s+report\b",
    r"\bclimate\s+report\b",
]

NOTICE_PATTERNS = [
    r"\bagm\b",
    r"\begm\b",
    r"\bnotice\s+of\s+(?:annual\s+general\s+)?meeting\b",
    r"\bproxy\s+form\b",
    r"\bcircular\b",
    r"\bdividend\s+announcement\b",
    r"\bpress\s+release\b",
    r"\bpresentation\b",
    r"\bfactsheet\b",
]

# Statements-only patterns (Components)
STATEMENTS_ONLY_PATTERNS = [
    r"\baudited\s+financial\s+statements\b",
    r"\bannual\s+financial\s+statements\b",
    r"\bfinancial\s+statements\s+for\s+the\s+year\s+ended\b",
    r"\bindependent\s+auditor'?s\s+report\s+and\s+financial\s+statements\b",
    r"\bfinancial\s+statements\b",
    r"\bfinancial\s+report\b",
]

# Full Annual Report positive patterns
FULL_AR_PATTERNS = [
    r"\bannual\s+report\s+and\s+(?:audited\s+)?financial\s+statements\b",
    r"\bintegrated\s+(?:annual\s+)?report\b",
    r"\bannual\s+report\b",
    r"\bannual\s+integrated\s+report\b",
    r"\bar\s+en\b",  # Oman MSX explicit tag
    r"\bannual\s+financial\s+report\b", # Jordan ASE full disclosure category
]

ARABIC_CHAR_PATTERN = re.compile(r"[\u0600-\u06FF]")


def detect_language(text: str, filename: str = "", metadata_lang: str = "") -> Tuple[str, float]:
    """Classify language as 'EN', 'AR', or 'BILINGUAL'.
    Only 'EN' or verified 'BILINGUAL' satisfies the _EN.pdf slot.
    """
    combined = f"{text} {filename} {metadata_lang}".lower()
    
    if "ar en" in combined or "en_" in combined or "_en" in combined or "english" in combined:
        return "EN", 0.98

    arabic_chars = len(ARABIC_CHAR_PATTERN.findall(text))
    total_chars = len(text.strip()) or 1
    arabic_ratio = arabic_chars / total_chars

    if arabic_ratio > 0.40:
        return "AR", 0.95
    elif arabic_ratio > 0.10:
        return "BILINGUAL", 0.85

    # Check for English tokens
    en_tokens = ["annual", "report", "financial", "statements", "company", "board", "auditor"]
    matches = sum(1 for t in en_tokens if t in combined)
    if matches >= 2:
        return "EN", 0.90

    return "EN", 0.70


def classify_document(title: str, url: str = "", source_tag: str = "") -> Tuple[str, float]:
    """Classify filing into:
    - 'AR_FULL': Full narrative annual report (or combined AR + FS)
    - 'ANNUAL_FS_COMPONENT': Audited annual financial statements only
    - 'GOVERNANCE_COMPONENT': Standalone governance report
    - 'ESG_COMPONENT': Standalone sustainability report
    - 'REJECT': Interim, AGM notice, proxy, dividend, circular
    """
    combined = f"{title} {url} {source_tag}".lower()

    # 1. Immediate rejection for interim & notices
    for pat in INTERIM_PATTERNS:
        if re.search(pat, combined):
            return "REJECT", 0.95
    for pat in NOTICE_PATTERNS:
        if re.search(pat, combined):
            return "REJECT", 0.95

    # 2. Standalone Governance / ESG
    for pat in GOVERNANCE_PATTERNS:
        if re.search(pat, combined) and not re.search(r"annual\s+report", combined):
            return "GOVERNANCE_COMPONENT", 0.90
    for pat in ESG_PATTERNS:
        if re.search(pat, combined) and not re.search(r"annual\s+report", combined):
            return "ESG_COMPONENT", 0.90

    # 3. Check for explicit Full Annual Report patterns
    for pat in FULL_AR_PATTERNS:
        if re.search(pat, combined):
            return "AR_FULL", 0.95

    # 4. Check for Statements-only component patterns
    for pat in STATEMENTS_ONLY_PATTERNS:
        if re.search(pat, combined):
            return "ANNUAL_FS_COMPONENT", 0.90

    # Default fallback: if it contains "annual" and "report", treat as AR_FULL
    if "annual" in combined and "report" in combined:
        return "AR_FULL", 0.80

    return "REJECT", 0.50
