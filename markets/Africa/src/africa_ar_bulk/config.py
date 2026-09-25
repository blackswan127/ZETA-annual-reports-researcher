from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

AFRICAN_MARKETS: Dict[str, Dict[str, Any]] = {
    "SouthAfrica": {
        "country": "South Africa",
        "iso3": "ZAF",
        "mic": "XJSE",
        "exchange": "Johannesburg Stock Exchange",
        "aliases": ["ZAF", "SOUTHAFRICA", "SOUTH AFRICA", "JSE"],
        "default_rps": 1.0,
    },
    "Nigeria": {
        "country": "Nigeria",
        "iso3": "NGA",
        "mic": "XNSA",
        "exchange": "Nigerian Exchange Group",
        "aliases": ["NGA", "NIGERIA", "NGX", "NSE_NGA"],
        "default_rps": 1.5,
    },
    "Kenya": {
        "country": "Kenya",
        "iso3": "KEN",
        "mic": "XNAI",
        "exchange": "Nairobi Securities Exchange",
        "aliases": ["KEN", "KENYA", "NSE_KEN", "NAIROBI"],
        "default_rps": 1.5,
    },
    "Ghana": {
        "country": "Ghana",
        "iso3": "GHA",
        "mic": "XGHA",
        "exchange": "Ghana Stock Exchange",
        "aliases": ["GHA", "GHANA", "GSE"],
        "default_rps": 1.0,
    },
    "Botswana": {
        "country": "Botswana",
        "iso3": "BWA",
        "mic": "XBOT",
        "exchange": "Botswana Stock Exchange",
        "aliases": ["BWA", "BOTSWANA", "BSE_BWA"],
        "default_rps": 1.0,
    },
    "Zambia": {
        "country": "Zambia",
        "iso3": "ZMB",
        "mic": "XLUS",
        "exchange": "Lusaka Securities Exchange",
        "aliases": ["ZMB", "ZAMBIA", "LUSE"],
        "default_rps": 1.0,
    },
    "Tanzania": {
        "country": "Tanzania",
        "iso3": "TZA",
        "mic": "XDAR",
        "exchange": "Dar es Salaam Stock Exchange",
        "aliases": ["TZA", "TANZANIA", "DSE_TZA"],
        "default_rps": 1.0,
    },
    "Zimbabwe": {
        "country": "Zimbabwe",
        "iso3": "ZWE",
        "mic": "XZIM",
        "exchange": "Zimbabwe Stock Exchange",
        "aliases": ["ZWE", "ZIMBABWE", "ZSE"],
        "default_rps": 1.0,
    },
    "Mauritius": {
        "country": "Mauritius",
        "iso3": "MUS",
        "mic": "XMAU",
        "exchange": "Stock Exchange of Mauritius",
        "aliases": ["MUS", "MAURITIUS", "SEM"],
        "default_rps": 1.0,
    },
    "Namibia": {
        "country": "Namibia",
        "iso3": "NAM",
        "mic": "XNAM",
        "exchange": "Namibian Stock Exchange",
        "aliases": ["NAM", "NAMIBIA", "NSX_NAM"],
        "default_rps": 1.0,
    },
    "Uganda": {
        "country": "Uganda",
        "iso3": "UGA",
        "mic": "XUGA",
        "exchange": "Uganda Securities Exchange",
        "aliases": ["UGA", "UGANDA", "USE"],
        "default_rps": 1.0,
    },
    "Malawi": {
        "country": "Malawi",
        "iso3": "MWI",
        "mic": "XMSW",
        "exchange": "Malawi Stock Exchange",
        "aliases": ["MWI", "MALAWI", "MSE"],
        "default_rps": 1.0,
    },
    "Rwanda": {
        "country": "Rwanda",
        "iso3": "RWA",
        "mic": "XRWA",
        "exchange": "Rwanda Stock Exchange",
        "aliases": ["RWA", "RWANDA", "RSE"],
        "default_rps": 1.0,
    },
    "Eswatini": {
        "country": "Eswatini",
        "iso3": "SWZ",
        "mic": "XSWA",
        "exchange": "Eswatini Stock Exchange",
        "aliases": ["SWZ", "ESWATINI", "SWAZILAND", "ESE"],
        "default_rps": 1.0,
    },
    "Seychelles": {
        "country": "Seychelles",
        "iso3": "SYC",
        "mic": "XMSX",
        "exchange": "MERJ Exchange",
        "aliases": ["SYC", "SEYCHELLES", "MERJ"],
        "default_rps": 1.0,
    },
    "SierraLeone": {
        "country": "Sierra Leone",
        "iso3": "SLE",
        "mic": "XSLS",
        "exchange": "Sierra Leone Stock Exchange",
        "aliases": ["SLE", "SIERRALEONE", "SIERRA LEONE", "SLSE"],
        "default_rps": 1.0,
    },
}


def resolve_african_market(query: str) -> Optional[Dict[str, Any]]:
    """Resolve country, MIC, or alias to canonical African market details."""
    norm = query.strip().upper().replace(" ", "").replace("_", "").replace("-", "")
    for canonical_name, data in AFRICAN_MARKETS.items():
        if canonical_name.upper() == norm:
            return {"canonical_name": canonical_name, **data}
        if data["iso3"] == norm:
            return {"canonical_name": canonical_name, **data}
        if data["mic"] == norm:
            return {"canonical_name": canonical_name, **data}
        for alias in data["aliases"]:
            if alias.replace(" ", "").replace("_", "").replace("-", "") == norm:
                return {"canonical_name": canonical_name, **data}
    return None


@dataclass
class RuntimeConfig:
    """Runtime configuration for Africa bulk harvester."""
    start_year: int = 2017
    end_year: int = 2025
    discovery_workers: int = 8
    download_workers: int = 16
    discovery_rps: float = 2.0
    download_rps: float = 6.0
    timeout: float = 45.0
    retries: int = 5
    min_pdf_bytes: int = 25000
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    work_dir: Path = field(default_factory=lambda: Path("work"))
    zeta_root: Path = field(default_factory=lambda: Path("GLOBAL_SUSTAINABILITY_DATABASE"))
