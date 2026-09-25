from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Tuple


def resolve_fy(
    text: str,
    metadata_period: str = "",
    publication_date: str = "",
) -> Tuple[Optional[int], float, str]:
    """Resolve the reporting fiscal year from filing text, metadata period, or publication date.
    Returns: (fiscal_year, confidence, method)
    """
    # 1. Explicit period end in metadata
    if metadata_period:
        m = re.search(r"\b(20(?:1[0-9]|2[0-9]))\b", metadata_period)
        if m:
            return int(m.group(1)), 1.0, "metadata_period_end"

    combined = f"{text}".strip()

    # 2. Explicit reporting period phrase in text: e.g. "year ended 31 December 2023"
    m = re.search(r"(?:year|period)\s+ended[^0-9]{0,30}(?:3[01]|30|[012]?[0-9])?[^0-9]{0,20}(20(?:1[0-9]|2[0-9]))", combined, re.I)
    if m:
        return int(m.group(1)), 0.99, "period_ended_phrase"

    # 3. Explicit FY token: FY2024, FY 2024, FY24
    m = re.search(r"\bFY\s*[-_/]?\s*(20\d{2})\b", combined, re.I)
    if m:
        return int(m.group(1)), 0.98, "explicit_fy4"

    m = re.search(r"\bFY\s*[-_/]?\s*(\d{2})\b", combined, re.I)
    if m:
        return 2000 + int(m.group(1)), 0.95, "explicit_fy2"

    # 4. Year range: 2023/24, 2023-2024, 2023/2024
    m = re.search(r"\b(20\d{2})\s*[-/]\s*(20\d{2}|\d{2})\b", combined)
    if m:
        a = int(m.group(1))
        b_str = m.group(2)
        b = int(b_str) if len(b_str) == 4 else (a // 100) * 100 + int(b_str)
        if a <= b <= a + 1:
            return b, 0.95, "year_range"

    # 5. Title year: "Annual Report 2023" or "2023 Annual Report"
    m = re.search(r"\b(20(?:1[0-9]|2[0-9]))\s+(?:annual|integrated)\b", combined, re.I)
    if m:
        return int(m.group(1)), 0.92, "year_before_title"

    m = re.search(r"\b(?:annual|integrated)\s+(?:report|accounts)?[^\d]{0,20}(20(?:1[0-9]|2[0-9]))\b", combined, re.I)
    if m:
        return int(m.group(1)), 0.90, "year_after_title"

    # 6. Generic year in title
    years = [int(y) for y in re.findall(r"\b(20(?:1[0-9]|2[0-9]))\b", combined)]
    if years:
        return max(years), 0.70, "generic_title_year"

    # 7. Fallback to publication date heuristic
    if publication_date:
        try:
            dt = datetime.fromisoformat(publication_date.replace("Z", "+00:00"))
            # African annual reports published Jan-June are usually for the previous calendar year
            fy = dt.year - 1 if dt.month <= 6 else dt.year
            return fy, 0.55, "publication_date_heuristic"
        except Exception:
            pass

    return None, 0.0, "unresolved"
