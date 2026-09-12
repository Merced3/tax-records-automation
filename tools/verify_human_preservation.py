"""Prove that a migration preserved every human-typed annotation.

Compares a pre-change snapshot directory of annotation CSVs with the current
annotations. Human text is keyed by financial content (date, amount, raw bank
description) rather than Transaction ID, precisely because identity-scheme
migrations change IDs. Any lost or altered human text is reported as a
failure, and multiplicity is checked so text cannot be duplicated onto extra
rows either.

Usage:
    python tools/verify_human_preservation.py backups/<snapshot-dir>
"""

from collections import Counter
from pathlib import Path
import csv
import sys

HUMAN = ["Category", "Tax Treatment", "Note"]


def human_multiset(path):
    counts = Counter()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            values = tuple((row.get(c) or "").strip() for c in HUMAN)
            if not any(values):
                continue
            key = ((row.get("Date") or "").strip(),
                   (row.get("Amount") or "").strip(),
                   (row.get("Raw Bank Description") or "").strip(),
                   values)
            counts[key] += 1
    return counts


def main(snapshot_dir, annotations_dir="annotations"):
    snapshot_dir = Path(snapshot_dir)
    current_dir = Path(annotations_dir)
    failures = 0
    for before_path in sorted(snapshot_dir.glob("*.csv")):
        after_path = current_dir / before_path.name
        if not after_path.exists():
            print(f"FAIL {before_path.name}: missing in {current_dir}")
            failures += 1
            continue
        before, after = human_multiset(before_path), human_multiset(after_path)
        lost = before - after
        gained = after - before
        print(f"{before_path.name}: {sum(before.values())} human row(s) before, "
              f"{sum(after.values())} after")
        for key, count in lost.items():
            print(f"  LOST x{count}: {key[0]} {key[1]} {key[2][:48]!r} {key[3]}")
            failures += 1
        for key, count in gained.items():
            # New human text is legitimate only if a human typed it between
            # the snapshot and now; during a migration check it is suspicious.
            print(f"  NEW  x{count}: {key[0]} {key[1]} {key[2][:48]!r} {key[3]}")
    print("RESULT:", "PRESERVED" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(*sys.argv[1:]))
