from dataclasses import dataclass

COUNTRY_ISO3 = "BGD"
EXCHANGE_MIC = "XDHA"
DEFAULT_START_YEAR = 2017
DEFAULT_END_YEAR = 2025
USER_AGENT = "ZETA-AI-DSE-Annual-Reports/1.0 (+research; respectful-rate-limits)"

@dataclass(frozen=True)
class RuntimeConfig:
    start_year: int = DEFAULT_START_YEAR
    end_year: int = DEFAULT_END_YEAR
    discovery_workers: int = 5
    download_workers: int = 8
    request_delay: float = 0.35
    timeout: int = 45
    max_retries: int = 5
    min_pdf_bytes: int = 8_000
