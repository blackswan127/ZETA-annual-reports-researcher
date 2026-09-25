"""Sources module for African annual report discovery."""

from .african_financials import AfricanFinancialsAdapter
from .base import BaseSourceAdapter
from .exchange_direct import DirectExchangeAdapter
from .issuer_ir import IssuerIRCrawler
from .universe import load_universe

__all__ = [
    "AfricanFinancialsAdapter",
    "BaseSourceAdapter",
    "DirectExchangeAdapter",
    "IssuerIRCrawler",
    "load_universe",
]
