import unittest
from datetime import datetime

from hkex_bulk.pipeline import normalize_filing
from hkex_bulk.utils import choose_canonical_code, infer_fiscal_year, parse_size_bytes, split_stock_codes


class CoreTests(unittest.TestCase):
    def test_stock_codes(self):
        self.assertEqual(split_stock_codes("00700<br/>80700"), ["00700", "80700"])
        self.assertEqual(choose_canonical_code(["80700", "00700"], {"80700", "00700"}), "00700")

    def test_year_from_title(self):
        fy, source, confidence = infer_fiscal_year("ANNUAL REPORT 2024", datetime(2025, 4, 30, 18, 0))
        self.assertEqual((fy, source, confidence), (2024, "title", "high"))

    def test_year_heuristic(self):
        fy, source, confidence = infer_fiscal_year("ANNUAL REPORT", datetime(2025, 4, 30, 18, 0))
        self.assertEqual(fy, 2024)
        self.assertEqual(confidence, "low")

    def test_size(self):
        self.assertEqual(parse_size_bytes("3MB"), 3 * 1024 * 1024)

    def test_normalize_known_shape(self):
        raw = {
            "NEWS_ID": "123",
            "TITLE": "Annual Report 2024",
            "LONG_TEXT": "Financial Statements/ESG Information - [Annual Report]",
            "STOCK_CODE": "00700<br/>80700",
            "STOCK_NAME": "TENCENT<br/>TENCENT-R",
            "DATE_TIME": "30/04/2025 18:25",
            "FILE_TYPE": "PDF",
            "FILE_INFO": "3MB",
            "FILE_LINK": "/listedco/listconews/sehk/2025/0430/example.pdf",
        }
        x = normalize_filing(raw, {"00700", "80700"})
        self.assertEqual(x["canonical_code"], "00700")
        self.assertEqual(x["fiscal_year"], 2024)
        self.assertEqual(x["current_listed"], 1)
        self.assertTrue(x["file_url"].startswith("https://www1.hkexnews.hk/"))
        self.assertGreater(x["score"], 100)


if __name__ == "__main__":
    unittest.main()
