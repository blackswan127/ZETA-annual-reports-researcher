from __future__ import annotations

import re
from pathlib import Path
from pypdf import PdfReader

from .models import Validation
from .util import is_pdf, sha256_file


def validate_pdf(path: Path, expected_year: int, min_bytes: int=50_000, min_pages: int=5) -> Validation:
    size=path.stat().st_size if path.exists() else 0
    if not is_pdf(path,5):
        return Validation("FAIL",size,None,"","FAIL","missing_pdf_signature")
    if size < min_bytes:
        return Validation("FAIL",size,None,sha256_file(path),"WARN",f"below_min_bytes:{size}")
    pages=None; semantic="WARN"; note=""
    try:
        reader=PdfReader(str(path),strict=False); pages=len(reader.pages)
        if pages < min_pages:
            return Validation("FAIL",size,pages,sha256_file(path),"WARN",f"below_min_pages:{pages}")
        texts=[]
        for idx in list(range(min(4,pages))) + ([pages-1] if pages>4 else []):
            try: texts.append(reader.pages[idx].extract_text() or "")
            except Exception: pass
        text=" ".join(texts).lower()
        has_annual=bool(re.search(r"annual report|report to shareholders|annual financial report",text))
        has_year=str(expected_year) in text
        semantic="PASS" if has_annual and has_year else "WARN"
        if semantic=="WARN": note="semantic_signal_incomplete"
    except Exception as exc:
        return Validation("FAIL",size,pages,sha256_file(path),"FAIL",f"pdf_parse_error:{exc}")
    return Validation("PASS",size,pages,sha256_file(path),semantic,note)
