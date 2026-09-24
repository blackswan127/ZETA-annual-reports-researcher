"""Fetch all London Stock Exchange (LSE Main Market and AIM) listed companies from Wikidata."""

import httpx
import json

sparql = """
SELECT DISTINCT ?item ?itemLabel ?ticker ?lei ?isin ?crn WHERE {
  { ?item wdt:P414 wd:Q171240 . } UNION { ?item wdt:P414 wd:Q272261 . }
  OPTIONAL { ?item wdt:P249 ?ticker . }
  OPTIONAL { ?item wdt:P1278 ?lei . }
  OPTIONAL { ?item wdt:P946 ?isin . }
  OPTIONAL { ?item wdt:P2627 ?crn . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT 5000
"""

def main():
    headers = {"User-Agent": "annual-reports-researcher/1.0 (khanholdings127@gmail.com)"}
    print("Querying Wikidata SPARQL endpoint for full LSE universe...", flush=True)
    try:
        r = httpx.get(
            "https://query.wikidata.org/sparql",
            params={"query": sparql, "format": "json"},
            headers=headers,
            timeout=60.0,
        )
        print(f"Status: {r.status_code}", flush=True)
        if r.status_code == 200:
            data = r.json().get("results", {}).get("bindings", [])
            print(f"Total LSE entries returned by Wikidata: {len(data)}", flush=True)
            with open("local/wikidata_lse_full_sparql.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print("Saved to local/wikidata_lse_full_sparql.json", flush=True)
        else:
            print("Response error:", r.text[:300])
    except Exception as e:
        print("SPARQL error:", e)

if __name__ == "__main__":
    main()
