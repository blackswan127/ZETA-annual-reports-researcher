from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..config import MIDDLE_EAST_MARKETS, EXCLUDED_MARKETS
from ..models import Issuer

logger = logging.getLogger(__name__)

# Representative seed universe across the 8 Middle Eastern markets
# (Excluding Palestine and Israel)
DEFAULT_MIDDLE_EAST_UNIVERSE = [
    # Oman (OMN / XMUS)
    {"iso3": "OMN", "mic": "XMUS", "ticker": "BKMB", "company_name": "Bank Muscat SAOG", "isin": "OM0000001004", "fiscal_year_end": "12-31"},
    {"iso3": "OMN", "mic": "XMUS", "ticker": "OTEL", "company_name": "Oman Telecommunications Company SAOG", "isin": "OM0000003026", "fiscal_year_end": "12-31"},
    {"iso3": "OMN", "mic": "XMUS", "ticker": "BKDB", "company_name": "Bank Dhofar SAOG", "isin": "OM0000001046", "fiscal_year_end": "12-31"},
    {"iso3": "OMN", "mic": "XMUS", "ticker": "NBOB", "company_name": "National Bank of Oman SAOG", "isin": "OM0000001020", "fiscal_year_end": "12-31"},
    {"iso3": "OMN", "mic": "XMUS", "ticker": "OMVS", "company_name": "Oman International Development & Investment Company SAOG", "isin": "OM0000001509", "fiscal_year_end": "12-31"},

    # Jordan (JOR / XAMM)
    {"iso3": "JOR", "mic": "XAMM", "ticker": "ARBK", "company_name": "Arab Bank Plc", "isin": "JO1100001015", "fiscal_year_end": "12-31"},
    {"iso3": "JOR", "mic": "XAMM", "ticker": "THBK", "company_name": "The Housing Bank for Trade and Finance", "isin": "JO1100101013", "fiscal_year_end": "12-31"},
    {"iso3": "JOR", "mic": "XAMM", "ticker": "JOPH", "company_name": "Jordan Phosphate Mines Co.", "isin": "JO1200001014", "fiscal_year_end": "12-31"},
    {"iso3": "JOR", "mic": "XAMM", "ticker": "APOT", "company_name": "Arab Potash Company", "isin": "JO1200101012", "fiscal_year_end": "12-31"},
    {"iso3": "JOR", "mic": "XAMM", "ticker": "JTEL", "company_name": "Jordan Telecommunications Company (Orange Jordan)", "isin": "JO1300001013", "fiscal_year_end": "12-31"},

    # UAE - Dubai (ARE / XDFM)
    {"iso3": "ARE", "mic": "XDFM", "ticker": "EMAAR", "company_name": "Emaar Properties PJSC", "isin": "AEE000301011", "fiscal_year_end": "12-31"},
    {"iso3": "ARE", "mic": "XDFM", "ticker": "EMIRATESNBD", "company_name": "Emirates NBD Bank PJSC", "isin": "AEE000801014", "fiscal_year_end": "12-31"},
    {"iso3": "ARE", "mic": "XDFM", "ticker": "DIB", "company_name": "Dubai Islamic Bank PJSC", "isin": "AEE000101015", "fiscal_year_end": "12-31"},
    {"iso3": "ARE", "mic": "XDFM", "ticker": "DEWA", "company_name": "Dubai Electricity and Water Authority PJSC", "isin": "AED001801011", "fiscal_year_end": "12-31"},
    {"iso3": "ARE", "mic": "XDFM", "ticker": "SALIK", "company_name": "Salik Company PJSC", "isin": "AEE011101014", "fiscal_year_end": "12-31"},

    # UAE - Abu Dhabi (ARE / XADS)
    {"iso3": "ARE", "mic": "XADS", "ticker": "FAB", "company_name": "First Abu Dhabi Bank PJSC", "isin": "AEA000201011", "fiscal_year_end": "12-31"},
    {"iso3": "ARE", "mic": "XADS", "ticker": "IHC", "company_name": "International Holding Company PJSC", "isin": "AEA002001013", "fiscal_year_end": "12-31"},
    {"iso3": "ARE", "mic": "XADS", "ticker": "EAND", "company_name": "Emirates Telecommunications Group Company PJSC (e&)", "isin": "AEA000601012", "fiscal_year_end": "12-31"},
    {"iso3": "ARE", "mic": "XADS", "ticker": "ADCB", "company_name": "Abu Dhabi Commercial Bank PJSC", "isin": "AEA000501014", "fiscal_year_end": "12-31"},
    {"iso3": "ARE", "mic": "XADS", "ticker": "ALDAR", "company_name": "Aldar Properties PJSC", "isin": "AEA000401017", "fiscal_year_end": "12-31"},

    # Saudi Arabia (SAU / XSAU)
    {"iso3": "SAU", "mic": "XSAU", "ticker": "2222", "company_name": "Saudi Arabian Oil Company (Saudi Aramco)", "isin": "SA14TG012N13", "fiscal_year_end": "12-31"},
    {"iso3": "SAU", "mic": "XSAU", "ticker": "1120", "company_name": "Al Rajhi Banking and Investment Corporation", "isin": "SA0007879113", "fiscal_year_end": "12-31"},
    {"iso3": "SAU", "mic": "XSAU", "ticker": "1180", "company_name": "The Saudi National Bank (SNB)", "isin": "SA13L050IE10", "fiscal_year_end": "12-31"},
    {"iso3": "SAU", "mic": "XSAU", "ticker": "2010", "company_name": "Saudi Basic Industries Corporation (SABIC)", "isin": "SA0007879089", "fiscal_year_end": "12-31"},
    {"iso3": "SAU", "mic": "XSAU", "ticker": "7010", "company_name": "Saudi Telecom Company (stc)", "isin": "SA0007879543", "fiscal_year_end": "12-31"},

    # Qatar (QAT / DSMD)
    {"iso3": "QAT", "mic": "DSMD", "ticker": "QNBK", "company_name": "Qatar National Bank QPSC", "isin": "QA0006929853", "fiscal_year_end": "12-31"},
    {"iso3": "QAT", "mic": "DSMD", "ticker": "IQCD", "company_name": "Industries Qatar QPSC", "isin": "QA000A0KD6K3", "fiscal_year_end": "12-31"},
    {"iso3": "QAT", "mic": "DSMD", "ticker": "QIBK", "company_name": "Qatar Islamic Bank QPSC", "isin": "QA0006929861", "fiscal_year_end": "12-31"},
    {"iso3": "QAT", "mic": "DSMD", "ticker": "ORDS", "company_name": "Ooredoo QPSC", "isin": "QA0001673894", "fiscal_year_end": "12-31"},
    {"iso3": "QAT", "mic": "DSMD", "ticker": "CBQK", "company_name": "The Commercial Bank PSQC", "isin": "QA0006929887", "fiscal_year_end": "12-31"},

    # Bahrain (BHR / XBAH)
    {"iso3": "BHR", "mic": "XBAH", "ticker": "AUB", "company_name": "Ahli United Bank BSC", "isin": "BH000A0EQ2Z3", "fiscal_year_end": "12-31"},
    {"iso3": "BHR", "mic": "XBAH", "ticker": "NBB", "company_name": "National Bank of Bahrain BSC", "isin": "BH0007879088", "fiscal_year_end": "12-31"},
    {"iso3": "BHR", "mic": "XBAH", "ticker": "ALBH", "company_name": "Aluminium Bahrain BSC (Alba)", "isin": "BH000A1CS7U2", "fiscal_year_end": "12-31"},
    {"iso3": "BHR", "mic": "XBAH", "ticker": "BATELCO", "company_name": "Bahrain Telecommunications Company BSC (Beyon)", "isin": "BH0007879096", "fiscal_year_end": "12-31"},
    {"iso3": "BHR", "mic": "XBAH", "ticker": "BBK", "company_name": "Bank of Bahrain and Kuwait BSC", "isin": "BH0007879070", "fiscal_year_end": "12-31"},

    # Kuwait (KWT / XKUW)
    {"iso3": "KWT", "mic": "XKUW", "ticker": "NBK", "company_name": "National Bank of Kuwait SAKP", "isin": "KW0EQ0100018", "fiscal_year_end": "12-31"},
    {"iso3": "KWT", "mic": "XKUW", "ticker": "KFH", "company_name": "Kuwait Finance House KSCP", "isin": "KW0EQ0100026", "fiscal_year_end": "12-31"},
    {"iso3": "KWT", "mic": "XKUW", "ticker": "ZAIN", "company_name": "Mobile Telecommunications Company KSCP (Zain)", "isin": "KW0EQ0100042", "fiscal_year_end": "12-31"},
    {"iso3": "KWT", "mic": "XKUW", "ticker": "AGLTY", "company_name": "Agility Public Warehousing Company KSCP", "isin": "KW0EQ0100083", "fiscal_year_end": "12-31"},
    {"iso3": "KWT", "mic": "XKUW", "ticker": "BOUBYAN", "company_name": "Boubyan Bank KSCP", "isin": "KW0EQ0100034", "fiscal_year_end": "12-31"},
]


def load_mappings(local_dir: Optional[Path] = None) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Scan local wikidata files for ticker -> LEI and ticker -> ISIN mappings."""
    ticker_to_lei: Dict[str, str] = {}
    ticker_to_isin: Dict[str, str] = {}
    search_dirs = [Path("local"), Path("../local"), Path("../../local")]
    if local_dir:
        search_dirs.insert(0, local_dir)

    for base in search_dirs:
        if not base.exists():
            continue
        for p in base.glob("wikidata*.json"):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        for item in data:
                            t = item.get("ticker", "")
                            isin = item.get("isin", "")
                            lei = item.get("lei", "")
                            if isinstance(t, dict): t = t.get("value", "")
                            if isinstance(isin, dict): isin = isin.get("value", "")
                            if isinstance(lei, dict): lei = lei.get("value", "")
                            t = str(t).strip().upper()
                            isin = str(isin).strip().upper()
                            lei = str(lei).strip().upper()
                            if t and lei and len(lei) == 20:
                                ticker_to_lei[t] = lei
                            if t and isin and len(isin) == 12:
                                ticker_to_isin[t] = isin
            except Exception:
                pass
    return ticker_to_lei, ticker_to_isin


def load_universe(
    iso3: Optional[str] = None,
    universe_csv: Optional[Path] = None,
    local_dir: Optional[Path] = None,
) -> List[Issuer]:
    """Load and normalize the active Middle Eastern equity universe.
    Enforces strict exclusion of Palestine and Israel.
    """
    lei_map, isin_map = load_mappings(local_dir)
    issuers: List[Issuer] = []

    raw_rows = []
    if universe_csv and Path(universe_csv).exists():
        with open(universe_csv, "r", encoding="utf-8-sig") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                raw_rows.append({
                    "iso3": r.get("iso3") or r.get("country_iso3") or r.get("country", ""),
                    "mic": r.get("mic") or r.get("exchange_mic", ""),
                    "ticker": r.get("ticker", ""),
                    "company_name": r.get("company_name") or r.get("name", ""),
                    "isin": r.get("isin", ""),
                    "lei": r.get("lei", ""),
                    "fiscal_year_end": r.get("fiscal_year_end", ""),
                    "universe_source": "CUSTOM_CSV",
                })
    else:
        raw_rows = DEFAULT_MIDDLE_EAST_UNIVERSE

    for row in raw_rows:
        country_code = row.get("iso3", "").strip().upper()
        # EXCLUDE Palestine & Israel
        if country_code in ("PSE", "ISR", "PALESTINE", "ISRAEL", "XPSX", "XTAE"):
            continue

        if iso3 and country_code != iso3.strip().upper():
            continue

        mic = row.get("mic", "").strip().upper()
        if mic in ("XPSX", "XTAE"):
            continue

        ticker = row.get("ticker", "").strip().upper()
        name = row.get("company_name", "").strip()
        isin = row.get("isin", "").strip().upper() or isin_map.get(ticker, "")
        lei = row.get("lei", "").strip().upper() or lei_map.get(ticker, "")
        fye = row.get("fiscal_year_end", "").strip()
        univ_source = row.get("universe_source", "OFFICIAL_SEED")

        if not ticker or not name:
            continue

        issuer_id = f"{country_code}:{mic}:{ticker}"
        issuers.append(Issuer(
            issuer_id=issuer_id,
            iso3=country_code,
            mic=mic,
            ticker=ticker,
            company_name=name,
            isin=isin,
            lei=lei,
            fiscal_year_end=fye,
            active=1,
            universe_source=univ_source,
        ))

    return sorted(issuers, key=lambda x: (x.iso3, x.ticker))
