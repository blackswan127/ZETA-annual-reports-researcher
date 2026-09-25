from __future__ import annotations

import re
from typing import Optional, Tuple

STRONG_ANNUAL_PATTERNS = [
    r"\bannual\s+report\s+(?:and|&)\s+financial\s+statements\b",
    r"\bintegrated\s+annual\s+report\b",
    r"\bannual\s+integrated\s+report\b",
    r"\bannual\s+report\s+(?:and|&)\s+accounts\b",
    r"\bannual\s+report\s+to\s+shareholders\b",
    r"\bannual\s+report\b",
    r"\bintegrated\s+report\b",
    r"\baudited\s+annual\s+financial\s+statements\b",
    r"\bannual\s+financial\s+statements\b",
]

EXCLUDE_PATTERNS = [
    r"\bhalf[- ]?year(?:ly)?\b",
    r"\binterim\b",
    r"\bquarter(?:ly)?\b",
    r"\bq[1-4]\b",
    r"\bannual\s+general\s+meeting\b",
    r"\bagm\b",
    r"\bnotice\s+of\s+meeting\b",
    r"\bproxy\s+form\b",
    r"\bproxy\s+statement\b",
    r"\bcircular\b",
    r"\babridged\s+results\b",
    r"\bpress\s+release\b",
    r"\bdividend\s+announcement\b",
    r"\bpresentation\b",
    r"\bfactsheet\b",
    r"\bsustainability\s+report\b",
    r"\besg\s+report\b",
    r"\bcorporate\s+governance\s+report\b",
    r"\bunaudited\b",
]


def classify_document(title: str, url: str = "", page_count: Optional[int] = None) -> Tuple[bool, str, float]:
    """Classify whether a title/document represents a genuine statutory annual report.
    Returns: (is_ar, classification_label, confidence_score)
    """
    text = f"{title} {url}".strip().lower()

    # 1. Check strong negatives first
    for neg in EXCLUDE_PATTERNS:
        if re.search(neg, text):
            # Special case: an integrated report that mentions governance inside the title is still an AR
            if "integrated annual report" in text or "annual report and financial statements" in text:
                if not any(re.search(x, text) for x in [r"\bhalf[- ]?year\b", r"\binterim\b", r"\bquarter\b", r"\bagm\b", r"\bproxy\b"]):
                    break
            return False, "OTHER", -100.0

    # 2. Check positive indicators
    score = 0.0
    for pat in STRONG_ANNUAL_PATTERNS:
        if re.search(pat, text):
            score = 90.0
            break

    if not score:
        if re.search(r"\bannual\b", text) and re.search(r"\bfinancials?\b", text):
            score = 65.0
        elif re.search(r"\bannual\b", text):
            score = 45.0
        else:
            return False, "OTHER", 0.0

    # 3. Page count heuristic
    if page_count is not None:
        if page_count >= 40:
            score += 10.0
        elif page_count >= 20:
            score += 5.0
        elif page_count <= 5:
            score -= 35.0

    is_ar = score >= 50.0
    label = "AR" if is_ar else "OTHER"
    return is_ar, label, min(100.0, max(0.0, score))
