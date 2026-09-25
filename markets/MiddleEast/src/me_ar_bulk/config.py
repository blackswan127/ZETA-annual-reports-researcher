from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Core 8 Middle Eastern markets (Explicitly excluding Palestine and Israel)
MIDDLE_EAST_MARKETS: Dict[str, Dict[str, Any]] = {
    "Oman": {
        "country": "Oman",
        "iso3": "OMN",
        "mic": "XMUS",
        "exchange": "Muscat Stock Exchange",
        "aliases": ["OMN", "OMAN", "MSX", "MUSCAT"],
        "default_rps": 1.5,
    },
    "Jordan": {
        "country": "Jordan",
        "iso3": "JOR",
        "mic": "XAMM",
        "exchange": "Amman Stock Exchange",
        "aliases": ["JOR", "JORDAN", "ASE", "AMMAN"],
        "default_rps": 1.5,
    },
    "UAEDubai": {
        "country": "United Arab Emirates",
        "iso3": "ARE",
        "mic": "XDFM",
        "exchange": "Dubai Financial Market",
        "aliases": ["ARE", "UAE", "DUBAI", "DFM", "UNITED ARAB EMIRATES"],
        "default_rps": 1.5,
    },
    "UAEAbuDhabi": {
        "country": "United Arab Emirates",
        "iso3": "ARE",
        "mic": "XADS",
        "exchange": "Abu Dhabi Securities Exchange",
        "aliases": ["ADX", "ABU DHABI", "ABUDHABI"],
        "default_rps": 1.5,
    },
    "SaudiArabia": {
        "country": "Saudi Arabia",
        "iso3": "SAU",
        "mic": "XSAU",
        "exchange": "Saudi Exchange",
        "aliases": ["SAU", "SAUDI", "SAUDI ARABIA", "SAUDIARABIA", "TADAWUL", "KSA"],
        "default_rps": 1.0,
    },
    "Qatar": {
        "country": "Qatar",
        "iso3": "QAT",
        "mic": "DSMD",
        "exchange": "Qatar Stock Exchange",
        "aliases": ["QAT", "QATAR", "QSE", "DSMD", "DOHA"],
        "default_rps": 1.0,
    },
    "Bahrain": {
        "country": "Bahrain",
        "iso3": "BHR",
        "mic": "XBAH",
        "exchange": "Bahrain Bourse",
        "aliases": ["BHR", "BAHRAIN", "BHB", "BAHRAIN BOURSE", "MANAMA"],
        "default_rps": 1.0,
    },
    "Kuwait": {
        "country": "Kuwait",
        "iso3": "KWT",
        "mic": "XKUW",
        "exchange": "Boursa Kuwait",
        "aliases": ["KWT", "KUWAIT", "BK", "BOURSA KUWAIT", "KSE"],
        "default_rps": 1.0,
    },
}

EXCLUDED_MARKETS = {
    "PALESTINE": "Excluded by directive",
    "PSE": "Excluded by directive",
    "PEX": "Excluded by directive",
    "XPSX": "Excluded by directive",
    "ISRAEL": "Excluded by directive",
    "ISR": "Excluded by directive",
    "TASE": "Excluded by directive",
    "XTAE": "Excluded by directive",
}


def resolve_middle_east_market(query: str) -> Optional[Dict[str, Any]]:
    """Resolve country, MIC, or alias to canonical Middle Eastern market details.
    Explicitly ignores Palestine and Israel.
    """
    norm = query.strip().upper().replace(" ", "").replace("_", "").replace("-", "")
    for excluded_key in EXCLUDED_MARKETS:
        if norm == excluded_key.replace(" ", ""):
            return None

    for canonical_name, data in MIDDLE_EAST_MARKETS.items():
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
    """Runtime configuration for Middle East bulk harvester."""
    start_year: int = 2017
    end_year: int = 2025
    discovery_workers: int = 8
    download_workers: int = 16
    discovery_rps: float = 2.0
    download_rps: float = 4.0
    timeout: float = 45.0
    retries: int = 5
    min_pdf_bytes: int = 35000
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    work_dir: Path = field(default_factory=lambda: Path("work"))
    zeta_root: Path = field(default_factory=lambda: Path("GLOBAL_SUSTAINABILITY_DATABASE"))
    required_class: str = "AR_FULL"
