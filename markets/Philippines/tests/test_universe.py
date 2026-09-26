import pytest
from phl_pse_bulk.universe import parse_company_directory_html

MOCK_DIRECTORY_HTML = """
<html>
<body>
<table class="list">
  <tbody>
    <tr>
      <td><a href="javascript:cmpyLink('148')">Ayala Corporation</a></td>
      <td>AC</td>
      <td>Holding Firms</td>
      <td>Holding Firms</td>
      <td>1906-01-01</td>
    </tr>
    <tr>
      <td><a href="javascript:cmpyLink('599')">SM Investments Corporation</a></td>
      <td>SM</td>
      <td>Holding Firms</td>
      <td>Holding Firms</td>
      <td>2005-03-22</td>
    </tr>
    <tr>
      <td><a href="javascript:cmpyLink('999')">First Metro Philippine Equity ETF</a></td>
      <td>FMETF</td>
      <td>Exchange Traded Funds</td>
      <td>ETF</td>
      <td>2013-12-02</td>
    </tr>
  </tbody>
</table>
</body>
</html>
"""


def test_parse_company_directory_html():
    rows = parse_company_directory_html(MOCK_DIRECTORY_HTML)
    assert len(rows) == 3

    assert rows[0]["cmpy_id"] == "148"
    assert rows[0]["ticker"] == "AC"
    assert rows[0]["company_name"] == "Ayala Corporation"

    assert rows[1]["cmpy_id"] == "599"
    assert rows[1]["ticker"] == "SM"

    assert rows[2]["ticker"] == "FMETF"
    assert rows[2]["sector"] == "Exchange Traded Funds"
