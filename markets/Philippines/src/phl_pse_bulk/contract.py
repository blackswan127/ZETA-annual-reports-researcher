from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

BASE_URL = "https://edge.pse.com.ph"


def allowed_pse_url(path_or_url: str) -> str:
    """Enforce SSRF boundary: derived URL must remain on https://edge.pse.com.ph."""
    u = urljoin(BASE_URL + "/", path_or_url)
    p = urlparse(u)
    if p.scheme != "https" or p.netloc != "edge.pse.com.ph":
        raise ValueError(f"Off-host PSE attachment URL refused: {u}")
    return u


def extract_fiscal_year(text: str) -> Optional[int]:
    """Extract exact fiscal year from Form 17-A body or disclosure text."""
    if not text:
        return None
    patterns = [
        r"For the fiscal year ended[\s\S]{0,80}?(20\d{2})",
        r"For the fiscal year ended\s*\|?\s*[A-Za-z]{3,9}\s+\d{1,2},\s*(20\d{2})",
        r"period ended\s*\|?\s*[A-Za-z]{3,9}\s+\d{1,2},\s*(20\d{2})",
        r"calendar year ended\s*\|?\s*[A-Za-z]{3,9}\s+\d{1,2},\s*(20\d{2})",
        r"SEC FORM 17-A[\s\S]{0,80}?(20\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            try:
                yr = int(m.group(1))
                if 2000 <= yr <= 2035:
                    return yr
            except Exception:
                pass
    return None


def is_annual_report_template(name: str, form: str = "") -> bool:
    """Check if template corresponds to statutory Annual Report (Form 17-A / 17-1)."""
    n = (name or "").strip().lower()
    f = (form or "").strip().lower()
    return n == "annual report" or f in {"17-1", "17-a"}


def classify_attachment(label: str) -> str:
    """
    Classify attachment into AR_FULL, SR, AR_COMPONENT, OTHER, or REVIEW.
    Only AR_FULL satisfies the canonical annual report slot (_AR_EN.pdf).
    SR satisfies the sustainability slot (_SR_EN.pdf).
    """
    s = (label or "").strip().lower()

    # Sustainability / ESG
    sustainability_kws = ["sustainability", "esg", "csr", "social responsibility", "climate", "environment"]
    if any(k in s for k in sustainability_kws):
        return "SR"

    # Reject / Non-annual other disclosures
    reject_kws = ["quarter", "17-q", "governance", "information statement", "agm", "proxy", "notice", "minutes"]
    if any(k in s for k in reject_kws):
        return "OTHER"

    # Full Annual Report (Form 17-A)
    full_kws = ["17-a", "annual report", "annual_report", "annual-report"]
    if any(k in s for k in full_kws):
        return "AR_FULL"

    # Component only (AFS, supplementary schedules, audit opinion)
    component_kws = ["financial statement", "audited financial", "supplementary schedule", "auditor", "afs"]
    if any(k in s for k in component_kws):
        return "AR_COMPONENT"

    return "REVIEW"


@dataclass
class PSEIssuer:
    issuer_id: str
    pse_company_id: str
    ticker: str
    company_name: str
    sector: str = ""
    subsector: str = ""
    listing_date: str = ""
    fiscal_year_end: str = ""
    website: str = ""
    isin: str = ""
    lei: str = ""
    active: int = 1
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PSEAttachment:
    attachment_id: str
    candidate_id: str
    file_id: str
    label: str
    classification: str
    download_url: str
    mime_type: str = "application/pdf"
    byte_size: int = 0


@dataclass
class PSEFiling:
    candidate_id: str
    issuer_id: str
    edge_no: str
    template_name: str
    form_number: str
    filing_date: str
    body_file_id: str
    fiscal_year: Optional[int]
    fy_confidence: float
    body_url: str
    viewer_url: str
    attachments: List[PSEAttachment] = field(default_factory=list)
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PSESlot:
    issuer_id: str
    fiscal_year: int
    report_type: str = "AR"  # AR or SR
    status: str = "PENDING"  # PENDING, DONE, UNRESOLVED, FAILED, STAGED_UNRESOLVED_IDENTITY
    selected_attachment_id: Optional[str] = None
    destination_path: Optional[str] = None
    sha256: Optional[str] = None
    page_count: int = 0
    file_size_bytes: int = 0
    reason: str = ""
