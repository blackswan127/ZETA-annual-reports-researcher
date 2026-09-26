from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple
import fitz  # PyMuPDF

from .client import PSEClient
from .config import Settings


def compute_sha256_and_size(path: Path) -> Tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


def validate_pdf_file(path: Path) -> Tuple[bool, int, str]:
    """Validate PDF integrity and page count via PyMuPDF."""
    if not path.exists() or path.stat().st_size < 100:
        return False, 0, "File missing or smaller than 100 bytes"

    try:
        with open(path, "rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                return False, 0, f"Invalid PDF signature: {header!r}"

        doc = fitz.open(path)
        if doc.is_encrypted:
            doc.close()
            return False, 0, "Encrypted PDF"
        page_count = doc.page_count
        doc.close()
        if page_count < 1:
            return False, 0, "Zero pages in PDF"
        return True, page_count, "OK"
    except Exception as e:
        return False, 0, f"PyMuPDF validation error: {str(e)}"


def build_zeta_destination_path(
    output_root: Path,
    iso3: str,
    mic: str,
    ticker: str,
    fiscal_year: int,
    lei: str,
    isin: str,
    report_type: str = "AR",
    lang: str = "EN",
) -> Path:
    """Construct canonical ZETA path: GLOBAL_SUSTAINABILITY_DATABASE/PHL/XPHS/<LEI>/<ISIN>/<Ticker>/FY<YYYY>/..."""
    lei_clean = lei.strip().upper() if lei and len(lei.strip()) == 20 else "NOLEI"
    isin_clean = isin.strip().upper() if isin and len(isin.strip()) == 12 else "NOISIN"
    fname = f"{lei_clean}_{iso3}_{mic}_{ticker}_{isin_clean}_FY{fiscal_year}_{report_type}_{lang}.pdf"
    return output_root / iso3 / mic / lei_clean / isin_clean / ticker / f"FY{fiscal_year}" / fname


class Downloader:
    def __init__(self, client: PSEClient, settings: Optional[Settings] = None):
        self.client = client
        self.settings = settings or Settings()

    async def download_and_promote(
        self,
        download_url: str,
        ticker: str,
        fiscal_year: int,
        lei: str,
        isin: str,
        report_type: str = "AR",
        output_root: Optional[Path] = None,
    ) -> Tuple[str, str, Optional[Path], str, int, int]:
        """
        Stream attachment, validate with PyMuPDF, and atomically promote.
        Returns: (status, reason, final_path, sha256, page_count, byte_size)
        """
        target_root = output_root or self.settings.output_root
        staging_dir = self.settings.staging_dir
        staging_dir.mkdir(parents=True, exist_ok=True)

        # Temporary staging path
        temp_dest = staging_dir / f"PHL_{ticker}_FY{fiscal_year}_{report_type}.pdf"

        try:
            part_path = await self.client.stream_download(download_url, temp_dest)
        except Exception as e:
            return "FAILED", f"Stream download error: {str(e)}", None, "", 0, 0

        # Validate part file
        valid, pages, val_err = validate_pdf_file(part_path)
        if not valid:
            part_path.unlink(missing_ok=True)
            return "FAILED", f"PDF validation failed: {val_err}", None, "", 0, 0

        sha256_hash, byte_size = compute_sha256_and_size(part_path)

        # Identity purity check
        has_valid_lei = bool(lei and len(lei.strip()) == 20)
        has_valid_isin = bool(isin and len(isin.strip()) == 12)

        if has_valid_lei and has_valid_isin:
            final_path = build_zeta_destination_path(
                output_root=target_root,
                iso3="PHL",
                mic="XPHS",
                ticker=ticker,
                fiscal_year=fiscal_year,
                lei=lei,
                isin=isin,
                report_type=report_type,
            )
            status = "PROMOTED"
            reason = "Validated and promoted to canonical ZETA corpus"
        else:
            final_path = staging_dir / "unresolved_identity" / "PHL" / f"PHL_{ticker}_FY{fiscal_year}_{report_type}_{sha256_hash[:10]}.pdf"
            status = "STAGED_UNRESOLVED_IDENTITY"
            reason = f"Missing valid LEI/ISIN (LEI: '{lei}', ISIN: '{isin}'); staged safely"

        final_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic rename or copy
        try:
            shutil.move(str(part_path), str(final_path))
        except Exception:
            shutil.copy2(str(part_path), str(final_path))
            part_path.unlink(missing_ok=True)

        return status, reason, final_path, sha256_hash, pages, byte_size
