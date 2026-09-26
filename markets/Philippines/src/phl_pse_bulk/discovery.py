from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

from .client import PSEClient
from .config import Settings
from .contract import (
    PSEAttachment,
    PSEFiling,
    classify_attachment,
    extract_fiscal_year,
    is_annual_report_template,
)


def parse_financial_reports_search_html(html: str) -> List[Dict[str, Any]]:
    """Parse report rows and extract edge_no and template metadata."""
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, Any]] = []

    table = soup.find("table", class_="list") or soup.find("table")
    if not table:
        return rows

    tbody = table.find("tbody") or table
    tr_elements = tbody.find_all("tr")

    for tr in tr_elements:
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        # Look for openDiscViewer link or function: onclick="openDiscViewer('edge_no')"
        edge_no = ""
        action_link = tr.find("a", href=re.compile(r"openDiscViewer|edge_no")) or tr.find("a", onclick=re.compile(r"openDiscViewer"))
        if action_link:
            text_target = action_link.get("href", "") + " " + action_link.get("onclick", "")
            m = re.search(r"['\"]([a-f0-9]{20,40})['\"]", text_target) or re.search(r"edge_no=([a-f0-9]+)", text_target)
            if m:
                edge_no = m.group(1)

        if not edge_no:
            for td in tds:
                m = re.search(r"openDiscViewer\(['\"]([a-f0-9]+)['\"]", td.decode_contents())
                if m:
                    edge_no = m.group(1)
                    break

        if not edge_no:
            continue

        template_name = tds[1].get_text(strip=True) if len(tds) > 1 else ""
        report_title = tds[2].get_text(strip=True) if len(tds) > 2 else ""
        filing_date = tds[3].get_text(strip=True) if len(tds) > 3 else ""

        rows.append({
            "edge_no": edge_no,
            "template_name": template_name,
            "report_title": report_title,
            "filing_date": filing_date,
        })
    return rows


def parse_disc_viewer_html(html: str) -> tuple[Optional[str], List[Dict[str, str]]]:
    """
    Parse openDiscViewer.do response.
    Returns: (body_file_id, list of attachment dicts with keys 'file_id' and 'label')
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1. Body iframe file_id
    body_file_id = None
    iframe = soup.find("iframe", src=re.compile(r"downloadHtml\.do\?file_id=(\d+)"))
    if iframe:
        m = re.search(r"file_id=(\d+)", iframe.get("src", ""))
        if m:
            body_file_id = m.group(1)

    if not body_file_id:
        m = re.search(r"downloadHtml\.do\?file_id=(\d+)", html)
        if m:
            body_file_id = m.group(1)

    # 2. Attachments from <select id="file_list"> or attachment links
    attachments = []
    select = soup.find("select", id=re.compile(r"file_list|attach", re.I))
    if select:
        for opt in select.find_all("option"):
            val = opt.get("value", "").strip()
            label = opt.get_text(strip=True)
            if val and val != "0":
                attachments.append({"file_id": val, "label": label})

    if not attachments:
        for a in soup.find_all("a", href=re.compile(r"downloadFile\.do\?file_id=(\d+)")):
            m = re.search(r"file_id=(\d+)", a.get("href", ""))
            if m:
                attachments.append({"file_id": m.group(1), "label": a.get_text(strip=True)})

    return body_file_id, attachments


class DiscoveryEngine:
    def __init__(self, client: PSEClient):
        self.client = client

    async def discover_issuer_filings(
        self,
        cmpy_id: str,
        ticker: str,
        from_date: str = "2017-01-01",
        to_date: str = "2026-06-30",
    ) -> List[PSEFiling]:
        filings: List[PSEFiling] = []
        if not cmpy_id:
            return filings

        # Primary: financialReports/search.ax
        try:
            search_html = await self.client.post_form(
                "/financialReports/search.ax",
                data={
                    "companyId": str(cmpy_id),
                    "fromDate": from_date,
                    "toDate": to_date,
                    "keyword": "",
                    "pageNo": "1",
                },
            )
        except Exception:
            return filings

        report_rows = parse_financial_reports_search_html(search_html)

        for row in report_rows:
            edge_no = row["edge_no"]
            template_name = row["template_name"]

            # Filter for Annual Report or Form 17-A
            if not is_annual_report_template(template_name, row.get("report_title", "")):
                continue

            viewer_url = f"/openDiscViewer.do?edge_no={edge_no}"
            try:
                viewer_html = await self.client.get_html(viewer_url)
            except Exception:
                continue

            body_file_id, raw_attachments = parse_disc_viewer_html(viewer_html)

            # Resolve exact FY from body HTML
            fiscal_year = None
            fy_confidence = 0.0
            body_url = f"/downloadHtml.do?file_id={body_file_id}" if body_file_id else ""

            if body_file_id:
                try:
                    body_html = await self.client.get_html(body_url)
                    fiscal_year = extract_fiscal_year(body_html)
                    if fiscal_year:
                        fy_confidence = 1.0
                except Exception:
                    pass

            # Fallback FY from title or date if body parse failed
            if not fiscal_year:
                fiscal_year = extract_fiscal_year(row.get("report_title", ""))
                if fiscal_year:
                    fy_confidence = 0.7

            candidate_id = f"PHL_{ticker}_{edge_no}"
            filing = PSEFiling(
                candidate_id=candidate_id,
                issuer_id=ticker,
                edge_no=edge_no,
                template_name=template_name,
                form_number="17-A",
                filing_date=row["filing_date"],
                body_file_id=body_file_id or "",
                fiscal_year=fiscal_year,
                fy_confidence=fy_confidence,
                body_url=body_url,
                viewer_url=viewer_url,
            )

            # Process attachments
            for att_raw in raw_attachments:
                f_id = att_raw["file_id"]
                lbl = att_raw["label"]
                classification = classify_attachment(lbl)
                download_url = f"/downloadFile.do?file_id={f_id}"

                filing.attachments.append(PSEAttachment(
                    attachment_id=f"{candidate_id}_att_{f_id}",
                    candidate_id=candidate_id,
                    file_id=f_id,
                    label=lbl,
                    classification=classification,
                    download_url=download_url,
                ))

            filings.append(filing)

        return filings
