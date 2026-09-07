"""Write transactions to one CSV per year.

Column names and order come from config.yaml — this file only knows how to
fulfill column names, not which ones exist or their order. Adding a column
later = one entry in FIELD_MAP + one line in config.
"""

import csv
import os

# Every column name the writers know how to fill.
FIELD_MAP = {
    "Amount": lambda t: f"{t.amount:.2f}",
    "Date": lambda t: t.date,
    "Merchant": lambda t: t.merchant,
    "Bank Description": lambda t: t.description,
    # Available but off by default (tax pro wants exactly 4 columns):
    "Account": lambda t: t.source_account,
    "Source File": lambda t: os.path.basename(t.source_file),
    "Fingerprint": lambda t: t.fingerprint,
}


def write_year_csv(transactions, columns, output_dir, year):
    unknown = [c for c in columns if c not in FIELD_MAP]
    if unknown:
        raise ValueError(f"config.yaml lists unknown columns: {unknown}. "
                         f"Known: {sorted(FIELD_MAP)}")

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{year}.csv")

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for t in transactions:
            writer.writerow([FIELD_MAP[c](t) for c in columns])

    return path
