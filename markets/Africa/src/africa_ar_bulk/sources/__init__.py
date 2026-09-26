"""Sources module for African annual report discovery."""

from .african_financials import AfricanFinancialsAdapter
from .archive_wayback import WaybackArchiveAdapter
from .base import BaseSourceAdapter
from .exchange_direct import DirectExchangeAdapter
from .issuer_ir import IssuerIRCrawler
from .spa_crawler import DynamicSPACrawler
from .universe import load_universe

__all__ = [
    "AfricanFinancialsAdapter",
    "BaseSourceAdapter",
    "DirectExchangeAdapter",
    "DynamicSPACrawler",
    "IssuerIRCrawler",
    "load_universe",
    "WaybackArchiveAdapter",
]
