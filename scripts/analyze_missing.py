import sqlite3
import os

conn = sqlite3.connect("local/harvest.sqlite3")
cur = conn.cursor()
cur.execute("SELECT relative_path, status, verified, bytes, sha256 FROM reports WHERE status='downloaded' OR verified=1")
rows = cur.fetchall()

root = os.path.abspath("GLOBAL_SUSTAINABILITY_DATABASE")
missing = []
for rel, st, v, b, s in rows:
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        missing.append((rel, st, v, b, s))

print(f"Total missing files: {len(missing)}")
countries = {}
for m in missing:
    c = m[0].split("\\")[0] if "\\" in m[0] else m[0].split("/")[0]
    countries[c] = countries.get(c, 0) + 1
print("Missing by country:", countries)

# For each missing file, check where it came from in the DB (candidate / source_url)
print("\nSample missing details:")
for m in missing[:10]:
    rel = m[0]
    cand = cur.execute("SELECT source_url, notes, accession_number FROM candidates WHERE relative_path=?", (rel,)).fetchone()
    print(f"  Path: {rel}")
    print(f"    Bytes in DB: {m[3]}, SHA: {m[4]}")
    if cand:
        print(f"    Source URL: {cand[0]}")
        print(f"    Accession: {cand[2]}")
        print(f"    Notes: {cand[1]}")
    else:
        print("    No candidate entry found.")

conn.close()
