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


def preview(transactions, path, suggester):
    """Dry-run: show what rules WOULD fill, writing nothing.

    Returns a list of (transaction, suggestion) for rows that are still blank
    AND would get a suggestion. The point: tune rules.yaml against this
    before letting it touch your real files.
    """
    existing = load_existing(path)
    out = []
    for t in transactions:
        prior = existing.get(t.fingerprint, Annotation())
        if prior.filled:
            continue  # human (or a prior run) already owns this row
        sugg = suggester(t)
        if sugg.filled:
            out.append((t, sugg))
    return out


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


def generate(transactions, path, suggester=None):
    """Write the annotation file for a year, preserving existing human work.

    suggester: optional callable(transaction) -> Annotation, used to fill
    cells the human has NOT already filled (rules engine). Human work always
    wins: a cell you typed is never overwritten by a suggestion.

    Returns (total, annotated, carried_over, suggested) counts.
    """
    existing = load_existing(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    total = annotated = carried = suggested = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        for t in transactions:
            total += 1
            prior = existing.get(t.fingerprint, Annotation())
            if t.fingerprint in existing and prior.filled:
                carried += 1

            category, note = prior.category, prior.note
            # Apply a rule suggestion only to cells still empty.
            if suggester is not None and not prior.filled:
                sugg = suggester(t)
                if sugg.filled:
                    suggested += 1
                    category = category or sugg.category
                    note = note or sugg.note

            if (category or note).strip():
                annotated += 1
            writer.writerow([
                t.fingerprint,
                t.date,
                f"{t.amount:.2f}",
                t.merchant,
                t.description,
                category,
                note,
            ])
    return total, annotated, carried, suggested
