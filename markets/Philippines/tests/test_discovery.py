import pytest
from phl_pse_bulk.discovery import (
    parse_disc_viewer_html,
    parse_financial_reports_search_html,
)

MOCK_SEARCH_HTML = """
<html>
<body>
<table class="list">
  <tbody>
    <tr>
      <td><a href="javascript:openDiscViewer('a1b2c3d4e5f6789012345678')">View</a></td>
      <td>Annual Report</td>
      <td>SEC Form 17-A Annual Report for the period ended Dec 31, 2024</td>
      <td>2025-04-15 09:30:00</td>
    </tr>
    <tr>
      <td><a href="/openDiscViewer.do?edge_no=b2c3d4e5f678901234567890">View</a></td>
      <td>Quarterly Report</td>
      <td>SEC Form 17-Q for Q1 2024</td>
      <td>2024-05-15 10:00:00</td>
    </tr>
  </tbody>
</table>
</body>
</html>
"""

MOCK_VIEWER_HTML = """
<html>
<body>
<iframe id="mainViewer" src="/downloadHtml.do?file_id=881234"></iframe>
<select id="file_list">
  <option value="0">-- Select Attachment --</option>
  <option value="99001">2024_SEC_Form_17-A_Annual_Report.pdf</option>
  <option value="99002">2024_Sustainability_Report.pdf</option>
  <option value="99003">Audited_Financial_Statements_2024.pdf</option>
</select>
</body>
</html>
"""


def test_parse_financial_reports_search_html():
    rows = parse_financial_reports_search_html(MOCK_SEARCH_HTML)
    assert len(rows) == 2
    assert rows[0]["edge_no"] == "a1b2c3d4e5f6789012345678"
    assert rows[0]["template_name"] == "Annual Report"

    assert rows[1]["edge_no"] == "b2c3d4e5f678901234567890"
    assert rows[1]["template_name"] == "Quarterly Report"


def test_parse_disc_viewer_html():
    body_id, attachments = parse_disc_viewer_html(MOCK_VIEWER_HTML)
    assert body_id == "881234"
    assert len(attachments) == 3

    assert attachments[0]["file_id"] == "99001"
    assert "Annual_Report" in attachments[0]["label"]

    assert attachments[1]["file_id"] == "99002"
    assert "Sustainability" in attachments[1]["label"]

    assert attachments[2]["file_id"] == "99003"
    assert "Audited_Financial" in attachments[2]["label"]
