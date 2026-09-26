from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Optional, Tuple

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


LEI_REGEX = re.compile(r"^[A-Z0-9]{20}$")
ISIN_REGEX = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def is_valid_lei(lei: str) -> bool:
    return bool(lei and LEI_REGEX.match(lei.strip().upper()))


def is_valid_isin(isin: str) -> bool:
    return bool(isin and ISIN_REGEX.match(isin.strip().upper()))


def sanitize_token(s: str) -> str:
    """Sanitize ticker or name token for directory/filename safety."""
    return re.sub(r"[^A-Za-z0-9_-]", "", s.strip())


def build_sop_relative_path(
    iso3: str,
    mic: str,
    lei: str,
    isin: str,
    ticker: str,
    fiscal_year: int,
    lang: str = "EN",
    report_type: str = "AR",
) -> Path:
    """Generate canonical SOP relative path:
    <ISO3>/<MIC>/<LEI>_<ISIN>_<Ticker>/FYyyyy/<LEI>_<ISO3>_<MIC>_<Ticker>_<ISIN>_FYyyyy_<ReportType>_<Language>.pdf
    """
    clean_iso3 = iso3.strip().upper()
    clean_mic = mic.strip().upper()
    clean_lei = lei.strip().upper()
    clean_isin = isin.strip().upper()
    clean_ticker = sanitize_token(ticker).upper()
    clean_report_type = report_type.strip().upper()
    clean_lang = lang.strip().upper()
    fy_folder = f"FY{fiscal_year}"
    company_folder = f"{clean_lei}_{clean_isin}_{clean_ticker}"
    filename = f"{clean_lei}_{clean_iso3}_{clean_mic}_{clean_ticker}_{clean_isin}_FY{fiscal_year}_{clean_report_type}_{clean_lang}.pdf"
    return Path(clean_iso3) / clean_mic / company_folder / fy_folder / filename


def to_extended_path(p: Path) -> Path:
    """Ensure path handles Windows MAX_PATH (>260 chars) gracefully using extended-length prefix."""
    p_abs = p.resolve()
    s = str(p_abs)
    if os.name == "nt" and not s.startswith("\\\\?\\") and not s.startswith("\\\\.\\"):
        return Path("\\\\?\\" + s)
    return p_abs


def compute_sha256_and_size(file_path: Path) -> Tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with open(file_path, "rb") as f:
        while chunk := f.read(64 * 1024):
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


def validate_pdf_bytes_or_file(
    source: bytes | Path, min_pages: int = 1
) -> Tuple[bool, int, str]:
    """In-RAM zero-copy PyMuPDF / pypdf structural and readability validation.
    Returns: (is_valid, page_count, reason_if_invalid)
    """
    data = source if isinstance(source, bytes) else None
    path = str(source) if isinstance(source, Path) else None

    # 1. Quick header check
    header = data[:10] if data else open(path, "rb").read(10)
    if b"%PDF-" not in header:
        return False, 0, "Missing '%PDF-' header signature"

    # 2. PyMuPDF fast validation
    if HAS_PYMUPDF:
        try:
            doc = fitz.open(stream=data, filetype="pdf") if data else fitz.open(path)
            pages = len(doc)
            if pages < min_pages:
                doc.close()
                return False, pages, f"Page count {pages} is below minimum {min_pages}"
            # Check first page renderability / text
            first_page = doc[0]
            _ = first_page.get_text("text")[:200]
            doc.close()
            return True, pages, "OK"
        except Exception as e:
            return False, 0, f"PyMuPDF error: {str(e)}"

    # 3. Fallback to pypdf
    if HAS_PYPDF:
        try:
            import io
            stream = io.BytesIO(data) if data else open(path, "rb")
            reader = PdfReader(stream)
            pages = len(reader.pages)
            if pages < min_pages:
                if not data: stream.close()
                return False, pages, f"Page count {pages} is below minimum {min_pages}"
            if not data: stream.close()
            return True, pages, "OK"
        except Exception as e:
            return False, 0, f"pypdf error: {str(e)}"

    return True, 1, "OK (parsers unavailable)"


def promote_pdf_to_corpus(
    source_pdf: Path,
    output_root: Path,
    staging_root: Path,
    iso3: str,
    mic: str,
    ticker: str,
    fiscal_year: int,
    lei: str = "",
    isin: str = "",
    lang: str = "EN",
    report_type: str = "AR",
) -> Tuple[str, str, Path]:
    """Promote a validated PDF file to GLOBAL_SUSTAINABILITY_DATABASE or local staging.
    Returns: (status, reason, final_path)
    status is one of:
      - 'PROMOTED': written to canonical SOP path in Drive
      - 'IDEMPOTENT_EXISTING': already exists in Drive with identical SHA-256
      - 'CONFLICT': already exists in Drive with DIFFERENT SHA-256 (routed to conflicts/)
      - 'STAGED_UNRESOLVED_IDENTITY': missing valid LEI or ISIN, safely staged locally
      - 'INVALID_PDF': failed PDF validation
    """
    if not source_pdf.exists():
        return "FAILED", f"Source PDF does not exist: {source_pdf}", source_pdf

    # Structural check
    valid, pages, reason = validate_pdf_bytes_or_file(source_pdf)
    if not valid:
        return "INVALID_PDF", reason, source_pdf

    src_hash, src_size = compute_sha256_and_size(source_pdf)

    # Check identity completeness (strictly enforce no fake LEI/ISIN)
    valid_lei = is_valid_lei(lei)
    valid_isin = is_valid_isin(isin)

    if not (valid_lei and valid_isin):
        # Stage locally
        clean_ticker = sanitize_token(ticker)
        clean_report_type = report_type.strip().upper()
        staged_rel = Path("unresolved_identity") / iso3 / mic / f"{clean_ticker}_FY{fiscal_year}" / f"{clean_ticker}_FY{fiscal_year}_{clean_report_type}_{lang}.pdf"
        target_path = staging_root / staged_rel
        target_ext = to_extended_path(target_path)
        target_ext.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(to_extended_path(source_pdf), target_ext)
        missing_reasons = []
        if not valid_lei: missing_reasons.append(f"LEI invalid or missing ('{lei}')")
        if not valid_isin: missing_reasons.append(f"ISIN invalid or missing ('{isin}')")
        return "STAGED_UNRESOLVED_IDENTITY", "; ".join(missing_reasons), target_path

    # Identity complete: target is GLOBAL_SUSTAINABILITY_DATABASE
    sop_rel = build_sop_relative_path(iso3, mic, lei, isin, ticker, fiscal_year, lang=lang, report_type=report_type)
    dest_path = output_root / sop_rel
    dest_ext = to_extended_path(dest_path)

    dest_ext.parent.mkdir(parents=True, exist_ok=True)

    if dest_ext.exists():
        dest_hash, _ = compute_sha256_and_size(dest_ext)
        if dest_hash == src_hash:
            return "IDEMPOTENT_EXISTING", "Identical hash already in corpus", dest_path
        else:
            # Different content for same SOP slot: route to conflict review queue
            conflict_path = staging_root / "conflicts" / sop_rel
            conflict_ext = to_extended_path(conflict_path)
            conflict_ext.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(to_extended_path(source_pdf), conflict_ext)
            return "CONFLICT", f"Conflicting file with differing SHA-256 ({src_hash} vs {dest_hash})", conflict_path

    # Atomic write to Drive: write .part on destination folder first, then atomic rename
    part_path = dest_path.with_suffix(".pdf.part")
    part_ext = to_extended_path(part_path)
    shutil.copy2(to_extended_path(source_pdf), part_ext)
    part_hash, _ = compute_sha256_and_size(part_ext)
    if part_hash != src_hash:
        part_ext.unlink(missing_ok=True)
        return "FAILED", "Integrity check failed during target transfer", dest_path

    os.replace(part_ext, dest_ext)
    return "PROMOTED", "Successfully promoted to SOP corpus", dest_path


def promote_pdf_bytes_to_corpus(
    pdf_bytes: bytes,
    output_root: Path,
    staging_root: Path,
    iso3: str,
    mic: str,
    ticker: str,
    fiscal_year: int,
    lei: str = "",
    isin: str = "",
    lang: str = "EN",
    report_type: str = "AR",
) -> Tuple[str, str, Path, str, int, int]:
    """In-RAM zero-copy PyMuPDF validation and atomic write to target corpus.
    Returns: (status, reason, final_path, sha256, page_count, size_bytes)
    """
    size_bytes = len(pdf_bytes)
    if size_bytes == 0:
        return "FAILED", "Zero-byte payload", Path(""), "", 0, 0

    # 1. In-RAM structural validation
    valid, pages, reason = validate_pdf_bytes_or_file(pdf_bytes)
    if not valid:
        return "INVALID_PDF", reason, Path(""), "", pages, size_bytes

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    # 2. Check identity completeness
    valid_lei = is_valid_lei(lei)
    valid_isin = is_valid_isin(isin)

    if not (valid_lei and valid_isin):
        clean_ticker = sanitize_token(ticker)
        clean_report_type = report_type.strip().upper()
        staged_rel = Path("unresolved_identity") / iso3 / mic / f"{clean_ticker}_FY{fiscal_year}" / f"{clean_ticker}_FY{fiscal_year}_{clean_report_type}_{lang}.pdf"
        target_path = staging_root / staged_rel
        target_ext = to_extended_path(target_path)
        target_ext.parent.mkdir(parents=True, exist_ok=True)
        with open(target_ext, "wb") as f:
            f.write(pdf_bytes)
        missing_reasons = []
        if not valid_lei: missing_reasons.append(f"LEI invalid or missing ('{lei}')")
        if not valid_isin: missing_reasons.append(f"ISIN invalid or missing ('{isin}')")
        return "STAGED_UNRESOLVED_IDENTITY", "; ".join(missing_reasons), target_path, sha256, pages, size_bytes

    # 3. Canonical SOP path in Drive
    sop_rel = build_sop_relative_path(iso3, mic, lei, isin, ticker, fiscal_year, lang=lang, report_type=report_type)
    dest_path = output_root / sop_rel
    dest_ext = to_extended_path(dest_path)
    dest_ext.parent.mkdir(parents=True, exist_ok=True)

    if dest_ext.exists():
        dest_hash, _ = compute_sha256_and_size(dest_ext)
        if dest_hash == sha256:
            return "IDEMPOTENT_EXISTING", "Identical hash already in corpus", dest_path, sha256, pages, size_bytes
        else:
            conflict_path = staging_root / "conflicts" / sop_rel
            conflict_ext = to_extended_path(conflict_path)
            conflict_ext.parent.mkdir(parents=True, exist_ok=True)
            with open(conflict_ext, "wb") as f:
                f.write(pdf_bytes)
            return "CONFLICT", f"Conflicting file with differing SHA-256 ({sha256} vs {dest_hash})", conflict_path, sha256, pages, size_bytes

    # 4. Atomic single-pass write to target: .part first, then atomic rename
    part_path = dest_path.with_suffix(".pdf.part")
    part_ext = to_extended_path(part_path)
    with open(part_ext, "wb") as f:
        f.write(pdf_bytes)

    part_hash, _ = compute_sha256_and_size(part_ext)
    if part_hash != sha256:
        part_ext.unlink(missing_ok=True)
        return "FAILED", "Integrity check failed during target transfer", dest_path, sha256, pages, size_bytes

    os.replace(part_ext, dest_ext)
    return "PROMOTED", "Successfully promoted to SOP corpus", dest_path, sha256, pages, size_bytes
