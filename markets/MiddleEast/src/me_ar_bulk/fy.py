from __future__ import annotations

import re
from typing import Optional, Tuple

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def resolve_fiscal_year(
    title: str = "",
    period_end: str = "",
    publication_date: str = "",
    url: str = "",
) -> Tuple[Optional[int], float, str]:
    """Deterministically resolve fiscal year from metadata, title, and period end.
    Returns (resolved_fy, confidence, resolution_method).
    """
    # 1. Explicit period end (Highest confidence)
    if period_end:
        m_iso = re.search(r"(20\d\d)[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])", period_end)
        if m_iso:
            y = int(m_iso.group(1))
            if 2010 <= y <= 2030:
                return y, 0.99, "EXPLICIT_PERIOD_END_ISO"

        m_dmy = re.search(r"(0?[1-9]|[12]\d|3[01])[-/](0?[1-9]|1[0-2])[-/](20\d\d)", period_end)
        if m_dmy:
            y = int(m_dmy.group(3))
            if 2010 <= y <= 2030:
                return y, 0.99, "EXPLICIT_PERIOD_END_DMY"

        m_text_date = re.search(r"(3[01]|[12]\d|0?[1-9])\s+([A-Za-z]+)\s+(20\d\d)", period_end)
        if m_text_date:
            month_str = m_text_date.group(2).lower()
            if month_str in MONTH_MAP:
                y = int(m_text_date.group(3))
                if 2010 <= y <= 2030:
                    return y, 0.99, "EXPLICIT_PERIOD_END_TEXT"

    combined = f"{title} {url}".strip()

    # 2. Explicit FY Token: 'FY2023', 'FY 2023', 'FY23'
    m_fy4 = re.search(r"\b(?:FY|F\.Y\.)\s*[:\-_]?\s*(20\d\d)\b", combined, re.IGNORECASE)
    if m_fy4:
        y = int(m_fy4.group(1))
        if 2010 <= y <= 2030:
            return y, 0.95, "EXPLICIT_FY_TOKEN_4DIGIT"

    m_fy2 = re.search(r"\b(?:FY|F\.Y\.)\s*[:\-_]?\s*(\d{2})\b", combined, re.IGNORECASE)
    if m_fy2:
        val = int(m_fy2.group(1))
        y = 2000 + val
        if 2010 <= y <= 2030:
            return y, 0.90, "EXPLICIT_FY_TOKEN_2DIGIT"

    # 3. Year Ranges: '2023/2024', '2023-2024', '2023/24', '2023-24'
    m_range = re.search(r"\b(20\d\d)\s*[-/]\s*(20\d\d)\b", combined)
    if m_range:
        y1, y2 = int(m_range.group(1)), int(m_range.group(2))
        if y2 == y1 + 1 or y2 == y1:
            return max(y1, y2), 0.95, "YEAR_RANGE_4DIGIT"

    m_range_short = re.search(r"\b(20\d\d)\s*[-/]\s*(\d{2})\b", combined)
    if m_range_short:
        y1 = int(m_range_short.group(1))
        short_y2 = int(m_range_short.group(2))
        y2 = (y1 // 100) * 100 + short_y2
        if y2 == y1 + 1 or y2 == y1:
            return max(y1, y2), 0.92, "YEAR_RANGE_SHORT"

    # 4. Standalone 4-digit Year in Title (between 2017 and 2025)
    years_found = [int(y) for y in re.findall(r"\b(20[12]\d)\b", title)]
    if years_found:
        # Prefer the most recent realistic year
        valid_years = [y for y in years_found if 2015 <= y <= 2026]
        if valid_years:
            return valid_years[-1], 0.85, "TITLE_STANDALONE_YEAR"

    # 5. Publication date heuristic (review required)
    if publication_date:
        m_pub = re.search(r"(20\d\d)", publication_date)
        if m_pub:
            pub_year = int(m_pub.group(1))
            # Annual reports published in Q1/Q2 usually belong to previous year
            return pub_year - 1, 0.60, "PUBLICATION_DATE_HEURISTIC"

    return None, 0.0, "UNRESOLVED"
