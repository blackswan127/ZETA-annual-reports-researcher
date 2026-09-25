import unittest
from datetime import date

from hkex_bulk.company_stats import parse_listed_company_count


class CompanyStatsTests(unittest.TestCase):
    def test_parses_official_month_end_company_count(self):
        html = """
        <h2>Overview of listed companies</h2>
        <table>
          <tr><td>Number of listed companies</td></tr>
          <tr><td>1. As at 1 January 2026</td><td>2,374</td><td>312</td><td>2,686</td></tr>
          <tr><td>2. Newly listed companies</td><td>104</td><td>2</td><td>106</td></tr>
          <tr><td>3. Delisted companies</td><td>23</td><td>8</td><td>31</td></tr>
          <tr><td>4. As at 31 August 2026</td><td>2,455</td><td>306</td><td>2,761</td></tr>
        </table>
        """
        self.assertEqual(
            parse_listed_company_count(html, date(2026, 8, 31)),
            {"main_board": 2455, "gem": 306, "total": 2761},
        )

    def test_rejects_nonmatching_or_inconsistent_count(self):
        html = """
        <h2>Overview of listed companies</h2>
        <p>Number of listed companies</p>
        <p>As at 31 August 2026 2,455 306 2,760</p>
        """
        self.assertIsNone(parse_listed_company_count(html, date(2026, 8, 31)))


if __name__ == "__main__":
    unittest.main()
