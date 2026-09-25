"""Retry failed reports that encountered temporary network or HTTP 503/timeout issues."""

from __future__ import annotations

import csv
import os
import sqlite3
from pathlib import Path

from annual_reports.catalog import FIELDS, Report
from annual_reports.engine import Settings, run


async def main():
    state_path = Path("local/harvest.sqlite3")
    output_root = Path("GLOBAL_SUSTAINABILITY_DATABASE")
    sec_user_agent = "blackswan capital khanholdings127@gmail.com"
    ch_api_key = os.getenv("COMPANIES_HOUSE_API_KEY", "82f00221-8dfb-40e7-9bb8-9e98603193f3")

    conn = sqlite3.connect(state_path)
    cur = conn.cursor()

    # Query failed reports
    rows = cur.execute(
        "SELECT relative_path, pdf_url, source_page, error FROM reports WHERE status='failed'"
    ).fetchall()
    conn.close()

    print(f"Total failed reports in database: {len(rows)}")

    # Exclude permanently unrecoverable errors: password protected, corrupted empty tree, 403
    unrecoverable = {"encrypted PDF requires a password", "response is not a PDF"}
    retryable_rows = [r for r in rows if r[3] not in unrecoverable and "exceeds max_mib" not in r[3]]
    print(f"Retryable candidates: {len(retryable_rows)}")

    # Convert relative paths back to Report objects
    # Format of relative_path: country/exchange/lei_isin_ticker/fiscal_year/filename
    reports_to_retry: list[Report] = []
    for rel, url, sp, err in retryable_rows:
        parts = rel.replace("\\", "/").split("/")
        if len(parts) < 5:
            continue
        country, exchange, co, fy, fn = parts[0], parts[1], parts[2], parts[3], parts[4]
        # Filename: lei_country_exchange_ticker_isin_fy_type_lang.pdf
        fn_parts = fn.replace(".pdf", "").split("_")
        if len(fn_parts) < 8:
            continue
        lei = fn_parts[0]
        ticker = fn_parts[3]
        isin = fn_parts[4]
        report_type = fn_parts[6]
        lang = fn_parts[7]

        try:
            rep = Report(
                country=country,
                exchange=exchange,
                lei=lei,
                isin=isin,
                ticker=ticker,
                fiscal_year=fy,
                report_type=report_type,
                language=lang,
                pdf_url=url,
                source_page=sp,
                verified=True,
            )
            reports_to_retry.append(rep)
        except Exception as e:
            print(f"Error parsing report {rel}: {e}")

    print(f"Built {len(reports_to_retry)} Report objects to retry.")
    if not reports_to_retry:
        return

    settings = Settings(
        output_root=output_root,
        state_path=state_path,
        workers=4,
        per_host=2,
        timeout_s=60.0,
        max_mib=250,  # bump max_mib to 250MB
        sec_user_agent=sec_user_agent,
        companies_house_key=ch_api_key,
    )

    summary = await run(reports_to_retry, settings)
    print("Retry summary:")
    import json
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
