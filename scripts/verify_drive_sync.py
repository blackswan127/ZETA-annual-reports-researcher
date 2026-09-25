"""Fast, multithreaded Drive presence and integrity verification."""

from __future__ import annotations

import concurrent.futures
import os
import sqlite3
import sys
import time
from pathlib import Path


def check_batch(batch: list[tuple[str, int, str]], output_root: str):
    missing = []
    zero_bytes = []
    size_mismatches = []
    valid = 0
    total_bytes = 0

    for rel, exp_bytes, exp_sha in batch:
        # Avoid Path object creation overhead in tight loop
        full_path = os.path.join(output_root, rel)
        try:
            st = os.stat(full_path)
            sz = st.st_size
            if sz == 0:
                zero_bytes.append(rel)
            else:
                valid += 1
                total_bytes += sz
                if exp_bytes and sz != exp_bytes:
                    size_mismatches.append((rel, sz, exp_bytes))
        except FileNotFoundError:
            missing.append(rel)
        except OSError as e:
            missing.append(f"{rel} (error: {e})")

    return valid, total_bytes, missing, zero_bytes, size_mismatches


def main():
    state_path = Path("local/harvest.sqlite3")
    output_root_str = os.path.abspath("GLOBAL_SUSTAINABILITY_DATABASE")
    gdrive_real_str = os.path.abspath("G:/My Drive/GLOBAL_SUSTAINABILITY_DATABASE")

    print(f"State SQLite : {state_path} (exists={state_path.exists()})", flush=True)
    print(f"Output Root  : {output_root_str} (exists={os.path.exists(output_root_str)})", flush=True)
    print(f"Drive Target : {gdrive_real_str} (exists={os.path.exists(gdrive_real_str)})", flush=True)

    conn = sqlite3.connect(state_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT relative_path, bytes, sha256 FROM reports WHERE status='downloaded'"
    )
    rows = cur.fetchall()
    conn.close()

    total_reports = len(rows)
    print(f"Total reports to verify on Drive: {total_reports:,}", flush=True)

    # Use ThreadPoolExecutor to parallelize I/O stat calls across 16 threads
    batch_size = 500
    batches = [rows[i : i + batch_size] for i in range(0, total_reports, batch_size)]
    print(f"Partitioned into {len(batches)} batches of {batch_size} files. Verifying across 16 workers...", flush=True)

    t0 = time.monotonic()
    total_valid = 0
    total_bytes = 0
    all_missing = []
    all_zero = []
    all_mismatch = []
    processed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(check_batch, b, output_root_str): len(b) for b in batches}
        for future in concurrent.futures.as_completed(futures):
            v, b_bytes, m, z, mm = future.result()
            total_valid += v
            total_bytes += b_bytes
            all_missing.extend(m)
            all_zero.extend(z)
            all_mismatch.extend(mm)
            processed += futures[future]
            if processed % 5000 < batch_size or processed == total_reports:
                pct = processed / total_reports * 100
                elapsed = time.monotonic() - t0
                rate = processed / max(0.01, elapsed)
                print(
                    f"Progress: {processed:,} / {total_reports:,} ({pct:.1f}%) | "
                    f"Valid: {total_valid:,} | Missing: {len(all_missing)} | Rate: {rate:.0f} files/s",
                    flush=True,
                )

    elapsed_total = time.monotonic() - t0
    print(f"\n=======================================================", flush=True)
    print(f"               DRIVE SYNC VERIFICATION RESULTS         ", flush=True)
    print(f"=======================================================", flush=True)
    print(f"Total Verified Reports in DB : {total_reports:,}", flush=True)
    print(f"Present & Valid on Drive     : {total_valid:,} ({total_valid / max(1, total_reports) * 100:.2f}%)", flush=True)
    print(f"Total Data Verified on Drive : {total_bytes / (1024**3):.2f} GB ({total_bytes:,} bytes)", flush=True)
    print(f"Missing Files                : {len(all_missing)}", flush=True)
    print(f"Zero-Byte Files              : {len(all_zero)}", flush=True)
    print(f"Size Mismatches              : {len(all_mismatch)}", flush=True)
    print(f"Verification Elapsed Time    : {elapsed_total:.2f}s ({total_reports / max(0.01, elapsed_total):.0f} files/s)", flush=True)
    print(f"=======================================================", flush=True)

    if all_missing:
        print(f"\nSample of missing files (first 20):", flush=True)
        for m in all_missing[:20]:
            print(f"   - {m}", flush=True)

    if all_zero:
        print(f"\nSample of zero-byte files (first 10):", flush=True)
        for z in all_zero[:10]:
            print(f"   - {z}", flush=True)

    if all_mismatch:
        print(f"\nSample of size mismatches (first 10):", flush=True)
        for mm in all_mismatch[:10]:
            print(f"   - {mm[0]}: on disk {mm[1]} vs expected {mm[2]}", flush=True)

    if all_missing:
        import json
        with open("local/missing_reports.json", "w") as f:
            json.dump(all_missing, f, indent=2)
        print(f"Saved {len(all_missing)} missing report paths to local/missing_reports.json", flush=True)


if __name__ == "__main__":
    main()
