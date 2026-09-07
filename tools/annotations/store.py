"""The annotation store: where human judgment lives.

Design intent (see docs/automation/decisions.md):

- The Google Sheet is an OUTPUT. Your annotations are an INPUT. Inputs live
  in files you own, not in a web app we don't control.
- One CSV per year in annotations/. The pipeline generates the transaction
  columns; you fill in Category and Note.
- The fingerprint column is the bridge: it lets the pipeline re-associate
  your annotations with the right transaction even after re-parsing,
  re-sorting, or statement changes. Re-running NEVER overwrites a row
  you've annotated.
"""

import csv
import os
from dataclasses import dataclass

# Columns the pipeline writes and manages (do not hand-edit these).
MACHINE_COLS = ["Fingerprint", "Date", "Amount", "Merchant", "Bank Description"]
# Columns the human owns.
HUMAN_COLS = ["Category", "Note"]

HEADER = MACHINE_COLS + HUMAN_COLS


@dataclass
class Annotation:
    category: str = ""
    note: str = ""

    @property
    def filled(self):
        return bool(self.category.strip() or self.note.strip())


def load_existing(path):
    """Read prior human work: fingerprint -> Annotation. Missing file = none."""
    if not os.path.isfile(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fp = (row.get("Fingerprint") or "").strip()
            if fp:
                out[fp] = Annotation(
                    category=row.get("Category", ""),
                    note=row.get("Note", ""),
                )
    return out


def generate(transactions, path):
    """Write the annotation file for a year, preserving existing human work.

    Returns (total, annotated, carried_over) counts.
    """
    existing = load_existing(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    total = annotated = carried = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        for t in transactions:
            total += 1
            prior = existing.get(t.fingerprint, Annotation())
            if prior.filled:
                annotated += 1
                if t.fingerprint in existing:
                    carried += 1
            writer.writerow([
                t.fingerprint,
                t.date,
                f"{t.amount:.2f}",
                t.merchant,
                t.description,
                prior.category,
                prior.note,
            ])
    return total, annotated, carried
