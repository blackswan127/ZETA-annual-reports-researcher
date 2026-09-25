from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..config import AFRICAN_MARKETS
from ..models import Issuer

logger = logging.getLogger(__name__)

# Representative seed universe across the 16 African markets
DEFAULT_AFRICAN_UNIVERSE = [
    # South Africa (ZAF / XJSE)
    {"country_iso3": "ZAF", "exchange_mic": "XJSE", "ticker": "NPN", "company_name": "Naspers Limited", "isin": "ZAE000015889", "fiscal_year_end": "03-31"},
    {"country_iso3": "ZAF", "exchange_mic": "XJSE", "ticker": "FSR", "company_name": "FirstRand Limited", "isin": "ZAE000066304", "fiscal_year_end": "06-30"},
    {"country_iso3": "ZAF", "exchange_mic": "XJSE", "ticker": "SBK", "company_name": "Standard Bank Group Limited", "isin": "ZAE000109815", "fiscal_year_end": "12-31"},
    {"country_iso3": "ZAF", "exchange_mic": "XJSE", "ticker": "SOL", "company_name": "Sasol Limited", "isin": "ZAE000006896", "fiscal_year_end": "06-30"},
    {"country_iso3": "ZAF", "exchange_mic": "XJSE", "ticker": "MTN", "company_name": "MTN Group Limited", "isin": "ZAE000042164", "fiscal_year_end": "12-31"},
    {"country_iso3": "ZAF", "exchange_mic": "XJSE", "ticker": "VOD", "company_name": "Vodacom Group Limited", "isin": "ZAE000132577", "fiscal_year_end": "03-31"},
    {"country_iso3": "ZAF", "exchange_mic": "XJSE", "ticker": "AMS", "company_name": "Anglo American Platinum Limited", "isin": "ZAE000013181", "fiscal_year_end": "12-31"},
    {"country_iso3": "ZAF", "exchange_mic": "XJSE", "ticker": "GFI", "company_name": "Gold Fields Limited", "isin": "ZAE000018123", "fiscal_year_end": "12-31"},
    {"country_iso3": "ZAF", "exchange_mic": "XJSE", "ticker": "SHP", "company_name": "Shoprite Holdings Limited", "isin": "ZAE000012084", "fiscal_year_end": "06-30"},
    {"country_iso3": "ZAF", "exchange_mic": "XJSE", "ticker": "DSY", "company_name": "Discovery Limited", "isin": "ZAE000022368", "fiscal_year_end": "06-30"},

    # Nigeria (NGA / XNSA)
    {"country_iso3": "NGA", "exchange_mic": "XNSA", "ticker": "DANGCEM", "company_name": "Dangote Cement Plc", "isin": "NGDANGCEM008", "fiscal_year_end": "12-31"},
    {"country_iso3": "NGA", "exchange_mic": "XNSA", "ticker": "MTNN", "company_name": "MTN Nigeria Communications Plc", "isin": "NGMTNN000002", "fiscal_year_end": "12-31"},
    {"country_iso3": "NGA", "exchange_mic": "XNSA", "ticker": "ZENITHBANK", "company_name": "Zenith Bank Plc", "isin": "NGZENITHB005", "fiscal_year_end": "12-31"},
    {"country_iso3": "NGA", "exchange_mic": "XNSA", "ticker": "GTCO", "company_name": "Guaranty Trust Holding Company Plc", "isin": "NGGTCO000002", "fiscal_year_end": "12-31"},
    {"country_iso3": "NGA", "exchange_mic": "XNSA", "ticker": "BUACEMENT", "company_name": "BUA Cement Plc", "isin": "NGBUACEM0000", "fiscal_year_end": "12-31"},
    {"country_iso3": "NGA", "exchange_mic": "XNSA", "ticker": "AIRTELAFRI", "company_name": "Airtel Africa Plc", "isin": "GB00BKDRSN58", "fiscal_year_end": "03-31"},
    {"country_iso3": "NGA", "exchange_mic": "XNSA", "ticker": "SEPLAT", "company_name": "Seplat Energy Plc", "isin": "NGSEPLAT0008", "fiscal_year_end": "12-31"},
    {"country_iso3": "NGA", "exchange_mic": "XNSA", "ticker": "NESTLE", "company_name": "Nestle Nigeria Plc", "isin": "NGNESTLE0006", "fiscal_year_end": "12-31"},

    # Kenya (KEN / XNAI)
    {"country_iso3": "KEN", "exchange_mic": "XNAI", "ticker": "SCOM", "company_name": "Safaricom Plc", "isin": "KE1000001402", "fiscal_year_end": "03-31"},
    {"country_iso3": "KEN", "exchange_mic": "XNAI", "ticker": "EQTY", "company_name": "Equity Group Holdings Plc", "isin": "KE0000000554", "fiscal_year_end": "12-31"},
    {"country_iso3": "KEN", "exchange_mic": "XNAI", "ticker": "KCB", "company_name": "KCB Group Plc", "isin": "KE0000000315", "fiscal_year_end": "12-31"},
    {"country_iso3": "KEN", "exchange_mic": "XNAI", "ticker": "EABL", "company_name": "East African Breweries Plc", "isin": "KE0000000216", "fiscal_year_end": "06-30"},
    {"country_iso3": "KEN", "exchange_mic": "XNAI", "ticker": "COOP", "company_name": "Co-operative Bank of Kenya Limited", "isin": "KE1000001568", "fiscal_year_end": "12-31"},
    {"country_iso3": "KEN", "exchange_mic": "XNAI", "ticker": "BAT", "company_name": "British American Tobacco Kenya Plc", "isin": "KE0000000075", "fiscal_year_end": "12-31"},
    {"country_iso3": "KEN", "exchange_mic": "XNAI", "ticker": "ABSA", "company_name": "Absa Bank Kenya Plc", "isin": "KE0000000067", "fiscal_year_end": "12-31"},

    # Ghana (GHA / XGHA)
    {"country_iso3": "GHA", "exchange_mic": "XGHA", "ticker": "MTNGH", "company_name": "Scancom Plc (MTN Ghana)", "isin": "GH0000001377", "fiscal_year_end": "12-31"},
    {"country_iso3": "GHA", "exchange_mic": "XGHA", "ticker": "SCB", "company_name": "Standard Chartered Bank Ghana Limited", "isin": "GH0000000098", "fiscal_year_end": "12-31"},
    {"country_iso3": "GHA", "exchange_mic": "XGHA", "ticker": "GCB", "company_name": "GCB Bank Limited", "isin": "GH0000000049", "fiscal_year_end": "12-31"},
    {"country_iso3": "GHA", "exchange_mic": "XGHA", "ticker": "TOTAL", "company_name": "TotalEnergies Marketing Ghana Plc", "isin": "GH0000000262", "fiscal_year_end": "12-31"},
    {"country_iso3": "GHA", "exchange_mic": "XGHA", "ticker": "FML", "company_name": "Fan Milk Limited", "isin": "GH0000000031", "fiscal_year_end": "12-31"},

    # Botswana (BWA / XBOT)
    {"country_iso3": "BWA", "exchange_mic": "XBOT", "ticker": "FNBB", "company_name": "First National Bank of Botswana Limited", "isin": "BW0000000059", "fiscal_year_end": "06-30"},
    {"country_iso3": "BWA", "exchange_mic": "XBOT", "ticker": "LETSHEGO", "company_name": "Letshego Holdings Limited", "isin": "BW0000000322", "fiscal_year_end": "12-31"},
    {"country_iso3": "BWA", "exchange_mic": "XBOT", "ticker": "SECHABA", "company_name": "Sechaba Brewery Holdings Limited", "isin": "BW0000000034", "fiscal_year_end": "12-31"},
    {"country_iso3": "BWA", "exchange_mic": "XBOT", "ticker": "SEFALANA", "company_name": "Sefalana Holding Company Limited", "isin": "BW0000000026", "fiscal_year_end": "04-30"},

    # Zambia (ZMB / XLUS)
    {"country_iso3": "ZMB", "exchange_mic": "XLUS", "ticker": "CEC", "company_name": "Copperbelt Energy Corporation Plc", "isin": "ZM0000000136", "fiscal_year_end": "12-31"},
    {"country_iso3": "ZMB", "exchange_mic": "XLUS", "ticker": "ZANACO", "company_name": "Zambia National Commercial Bank Plc", "isin": "ZM0000000250", "fiscal_year_end": "12-31"},
    {"country_iso3": "ZMB", "exchange_mic": "XLUS", "ticker": "ZAMBREW", "company_name": "Zambian Breweries Plc", "isin": "ZM0000000086", "fiscal_year_end": "12-31"},
    {"country_iso3": "ZMB", "exchange_mic": "XLUS", "ticker": "ATEL", "company_name": "Airtel Networks Zambia Plc", "isin": "ZM0000000342", "fiscal_year_end": "12-31"},

    # Tanzania (TZA / XDAR)
    {"country_iso3": "TZA", "exchange_mic": "XDAR", "ticker": "TBL", "company_name": "Tanzania Breweries Limited", "isin": "TZ1996100008", "fiscal_year_end": "12-31"},
    {"country_iso3": "TZA", "exchange_mic": "XDAR", "ticker": "CRDB", "company_name": "CRDB Bank Plc", "isin": "TZ1996101659", "fiscal_year_end": "12-31"},
    {"country_iso3": "TZA", "exchange_mic": "XDAR", "ticker": "NMB", "company_name": "NMB Bank Plc", "isin": "TZ1996100149", "fiscal_year_end": "12-31"},
    {"country_iso3": "TZA", "exchange_mic": "XDAR", "ticker": "TPCC", "company_name": "Tanzania Portland Cement Plc", "isin": "TZ1996100065", "fiscal_year_end": "12-31"},

    # Zimbabwe (ZWE / XZIM)
    {"country_iso3": "ZWE", "exchange_mic": "XZIM", "ticker": "DLTA", "company_name": "Delta Corporation Limited", "isin": "ZW0009011199", "fiscal_year_end": "03-31"},
    {"country_iso3": "ZWE", "exchange_mic": "XZIM", "ticker": "ECO", "company_name": "Econet Wireless Zimbabwe Limited", "isin": "ZW0009012122", "fiscal_year_end": "02-28"},
    {"country_iso3": "ZWE", "exchange_mic": "XZIM", "ticker": "CBZ", "company_name": "CBZ Holdings Limited", "isin": "ZW0009012098", "fiscal_year_end": "12-31"},
    {"country_iso3": "ZWE", "exchange_mic": "XZIM", "ticker": "INN", "company_name": "Innscor Africa Limited", "isin": "ZW0009011397", "fiscal_year_end": "06-30"},

    # Mauritius (MUS / XMAU)
    {"country_iso3": "MUS", "exchange_mic": "XMAU", "ticker": "MCB", "company_name": "MCB Group Limited", "isin": "MU0426N00004", "fiscal_year_end": "06-30"},
    {"country_iso3": "MUS", "exchange_mic": "XMAU", "ticker": "SBM", "company_name": "SBM Holdings Ltd", "isin": "MU0444N00000", "fiscal_year_end": "12-31"},
    {"country_iso3": "MUS", "exchange_mic": "XMAU", "ticker": "IBL", "company_name": "IBL Ltd", "isin": "MU0522N00018", "fiscal_year_end": "06-30"},

    # Namibia (NAM / XNAM)
    {"country_iso3": "NAM", "exchange_mic": "XNAM", "ticker": "CGP", "company_name": "Capricorn Group Limited", "isin": "NA000A1T6SV9", "fiscal_year_end": "06-30"},
    {"country_iso3": "NAM", "exchange_mic": "XNAM", "ticker": "NBS", "company_name": "Namibia Breweries Limited", "isin": "NA0009114944", "fiscal_year_end": "06-30"},

    # Uganda (UGA / XUGA)
    {"country_iso3": "UGA", "exchange_mic": "XUGA", "ticker": "SBU", "company_name": "Stanbic Bank Uganda Limited", "isin": "UG0000000386", "fiscal_year_end": "12-31"},
    {"country_iso3": "UGA", "exchange_mic": "XUGA", "ticker": "UMEM", "company_name": "Umeme Limited", "isin": "UG0000001145", "fiscal_year_end": "12-31"},

    # Malawi (MWI / XMSW)
    {"country_iso3": "MWI", "exchange_mic": "XMSW", "ticker": "NBM", "company_name": "National Bank of Malawi Plc", "isin": "MWNBM0010074", "fiscal_year_end": "12-31"},
    {"country_iso3": "MWI", "exchange_mic": "XMSW", "ticker": "STANDARD", "company_name": "Standard Bank Malawi Plc", "isin": "MWSTB0010083", "fiscal_year_end": "12-31"},

    # Rwanda (RWA / XRWA)
    {"country_iso3": "RWA", "exchange_mic": "XRWA", "ticker": "BOK", "company_name": "Bank of Kigali Group Plc", "isin": "RW000A1JCYA5", "fiscal_year_end": "12-31"},
    {"country_iso3": "RWA", "exchange_mic": "XRWA", "ticker": "BLR", "company_name": "Bralirwa Plc", "isin": "RW000A1H63U1", "fiscal_year_end": "12-31"},

    # Eswatini (SWZ / XSWA)
    {"country_iso3": "SWZ", "exchange_mic": "XSWA", "ticker": "NEDBANK", "company_name": "Nedbank Eswatini Limited", "isin": "SZ0005791338", "fiscal_year_end": "12-31"},

    # Seychelles (SYC / XMSX)
    {"country_iso3": "SYC", "exchange_mic": "XMSX", "ticker": "MERJ", "company_name": "MERJ Exchange Limited", "isin": "SC2529DAGA69", "fiscal_year_end": "12-31"},

    # Sierra Leone (SLE / XSLS)
    {"country_iso3": "SLE", "exchange_mic": "XSLS", "ticker": "RCBANK", "company_name": "Rokel Commercial Bank", "isin": "", "fiscal_year_end": "12-31"},
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
    country_iso3: Optional[str] = None,
    universe_csv: Optional[Path] = None,
    local_dir: Optional[Path] = None,
) -> List[Issuer]:
    """Load and normalize the active equity universe."""
    lei_map, isin_map = load_mappings(local_dir)
    issuers: List[Issuer] = []

    raw_rows = []
    target_csv = None
    if universe_csv and Path(universe_csv).exists():
        target_csv = Path(universe_csv)
    else:
        candidates = [
            Path("markets/Africa/local/african_equity_universe.csv"),
            Path("local/african_equity_universe.csv"),
            Path("../local/african_equity_universe.csv"),
        ]
        target_csv = next((p for p in candidates if p.exists()), None)

    if target_csv:
        with open(target_csv, "r", encoding="utf-8-sig") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                raw_rows.append({
                    "country_iso3": r.get("country_iso3") or r.get("country", ""),
                    "exchange_mic": r.get("exchange_mic") or r.get("mic", ""),
                    "ticker": r.get("ticker", ""),
                    "company_name": r.get("company_name") or r.get("name", ""),
                    "isin": r.get("isin", ""),
                    "lei": r.get("lei", ""),
                    "fiscal_year_end": r.get("fiscal_year_end", ""),
                    "source_url": r.get("source_url", ""),
                })
    else:
        raw_rows = DEFAULT_AFRICAN_UNIVERSE

    for row in raw_rows:
        iso3 = row.get("country_iso3", "").strip().upper()
        if country_iso3 and iso3 != country_iso3.strip().upper():
            continue
        mic = row.get("exchange_mic", "").strip().upper()
        ticker = row.get("ticker", "").strip().upper()
        name = row.get("company_name", "").strip()
        isin = row.get("isin", "").strip().upper() or isin_map.get(ticker, "")
        lei = row.get("lei", "").strip().upper() or lei_map.get(ticker, "")
        fye = row.get("fiscal_year_end", "").strip()
        source_url = row.get("source_url", "").strip()

        if not ticker or not name:
            continue

        issuer_id = f"{iso3}:{mic}:{ticker}"
        issuers.append(Issuer(
            issuer_id=issuer_id,
            country_iso3=iso3,
            exchange_mic=mic,
            ticker=ticker,
            company_name=name,
            isin=isin,
            lei=lei,
            fiscal_year_end=fye,
            active=1,
            source_url=source_url,
        ))

    return sorted(issuers, key=lambda x: (x.country_iso3, x.ticker))
