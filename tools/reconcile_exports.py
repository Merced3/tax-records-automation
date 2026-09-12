"""Prove the calendar-year view conserves exactly the rows it should.

The statement view and the calendar-year view are two groupings of the same
accepted transactions. Regrouping must not create, lose, or duplicate money.
For a tax year Y this checks, using Transaction IDs and amounts:

    calendar-year(Y) == every row dated in Y across all statement-folder
                        raw exports, with identical amounts and no duplicates

Run `python run.py build` for each year and `python run.py calendar-year Y`
first, then:

    python tools/reconcile_exports.py 2023
"""

from collections import Counter
from decimal import Decimal
from pathlib import Path
import csv
import sys


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(year, output_dir="output"):
    year = str(int(year))
    out = Path(output_dir)
    calendar_path = out / "calendar-year-raw" / f"{year}.csv"
    if not calendar_path.exists():
        print(f"missing {calendar_path}; run: python run.py calendar-year {year}")
        return 1

    calendar = read(calendar_path)
    expected = {}
    sources = {}
    for statement_csv in sorted((out / "raw").glob("*.csv")):
        for row in read(statement_csv):
            if row["Date"][-4:] != year:
                continue
            expected[row["Transaction ID"]] = row
            sources[row["Transaction ID"]] = statement_csv.name

    failures = 0
    calendar_ids = Counter(r["Transaction ID"] for r in calendar)
    duplicates = {i: c for i, c in calendar_ids.items() if c > 1}
    if duplicates:
        print(f"FAIL duplicated in calendar view: {len(duplicates)} id(s)")
        failures += len(duplicates)

    missing = set(expected) - set(calendar_ids)
    extra = set(calendar_ids) - set(expected)
    for transaction_id in sorted(missing):
        row = expected[transaction_id]
        print(f"FAIL missing from calendar view: {row['Date']} {row['Amount']} "
              f"{row['Merchant'][:40]} (from {sources[transaction_id]})")
        failures += 1
    for transaction_id in sorted(extra):
        row = next(r for r in calendar if r["Transaction ID"] == transaction_id)
        print(f"FAIL in calendar view but not dated {year} in any statement "
              f"export: {row['Date']} {row['Amount']} {row['Merchant'][:40]}")
        failures += 1

    for transaction_id in sorted(set(expected) & set(calendar_ids)):
        row = next(r for r in calendar if r["Transaction ID"] == transaction_id)
        if Decimal(row["Amount"]) != Decimal(expected[transaction_id]["Amount"]):
            print(f"FAIL amount changed for {transaction_id}: "
                  f"{expected[transaction_id]['Amount']} -> {row['Amount']}")
            failures += 1

    calendar_total = sum((Decimal(r["Amount"]) for r in calendar), Decimal("0.00"))
    expected_total = sum((Decimal(r["Amount"]) for r in expected.values()), Decimal("0.00"))
    print(f"statement view rows dated {year}: {len(expected)}, total {expected_total}")
    print(f"calendar-year view rows:          {len(calendar)}, total {calendar_total}")
    if calendar_total != expected_total:
        print("FAIL totals differ")
        failures += 1

    contributions = Counter(sources[i] for i in expected if i in calendar_ids)
    for name, count in sorted(contributions.items()):
        print(f"  contributed by {name}: {count} row(s)")

    print("RESULT:", "CONSERVED" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(*sys.argv[1:]))
