from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

LEI_REGEX = re.compile(r"^[A-Z0-9]{20}$")
ISIN_REGEX = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def is_valid_lei(lei: str) -> bool:
    return bool(lei and LEI_REGEX.match(lei.strip().upper()))


def is_valid_isin(isin: str) -> bool:
    return bool(isin and ISIN_REGEX.match(isin.strip().upper()))


def sanitize_token(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", s.strip())


def build_final_path(
    zeta_root: Path,
    iso3: str,
    mic: str,
    lei: str,
    isin: str,
    ticker: str,
    fiscal_year: int,
    lang: str = "EN",
    report_type: str = "AR",
) -> Optional[Path]:
    """Build canonical ZETA path:
    GLOBAL_SUSTAINABILITY_DATABASE/<ISO3>/<MIC>/<LEI>_<ISIN>_<Ticker>/FYyyyy/<LEI>_<ISO3>_<MIC>_<Ticker>_<ISIN>_FYyyyy_<REPORT_TYPE>_<LANG>.pdf
    Returns None if LEI or ISIN is missing or invalid.
    """
    clean_lei = lei.strip().upper()
    clean_isin = isin.strip().upper()
    if not (is_valid_lei(clean_lei) and is_valid_isin(clean_isin)):
        return None

    clean_iso3 = sanitize_token(iso3).upper()
    clean_mic = sanitize_token(mic).upper()
    clean_ticker = sanitize_token(ticker).upper()
    clean_lang = sanitize_token(lang).upper()
    clean_rep = sanitize_token(report_type).upper()

    company_folder = f"{clean_lei}_{clean_isin}_{clean_ticker}"
    fy_folder = f"FY{fiscal_year}"
    filename = f"{clean_lei}_{clean_iso3}_{clean_mic}_{clean_ticker}_{clean_isin}_FY{fiscal_year}_{clean_rep}_{clean_lang}.pdf"
    return Path(zeta_root) / clean_iso3 / clean_mic / company_folder / fy_folder / filename


def build_staging_path(
    staging_root: Path,
    iso3: str,
    mic: str,
    ticker: str,
    fiscal_year: int,
    lang: str = "EN",
    report_type: str = "AR",
) -> Path:
    """Build temporary local staging path for documents with unresolved LEI/ISIN."""
    clean_iso3 = sanitize_token(iso3).upper()
    clean_mic = sanitize_token(mic).upper()
    clean_ticker = sanitize_token(ticker).upper()
    clean_lang = sanitize_token(lang).upper()
    clean_rep = sanitize_token(report_type).upper()

    return Path(staging_root) / "unresolved_identity" / clean_iso3 / clean_mic / f"{clean_ticker}_FY{fiscal_year}" / f"{clean_ticker}_FY{fiscal_year}_{clean_rep}_{clean_lang}.pdf"


def promote_part_file(part_file: Path, final_target: Path) -> None:
    """Atomically promote a verified .part file to its final destination."""
    final_target = Path(final_target)
    final_target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(part_file, final_target)
