"""Annotation reporting: which rows still need a human?

Design intent (decoupled — see decisions.md):

- `unannotated()` is a PURE function: (transactions, annotations, options) ->
  rows. It does no printing, no file I/O beyond what callers hand it, and
  nothing about CSVs or Discord. A future Discord bot, a TUI, or a scheduled
  job all call this same function and render the result however they like.
- Ordering is pluggable via the `order` key, so "highest first" today and
  "least first" (or by merchant, or by date, or something we haven't thought
  of) tomorrow are just different entries in ORDERINGS — the query logic
  doesn't change.
- Direction is explicit (largest expenses first) because that's what matters
  for tax write-offs, but it's a parameter, not a hardcode.
"""

from datetime import datetime


def _amount_key(row):
    return abs(row["amount"])


# Registry of orderings. Each maps a row dict -> sort key. Add new ones here.
ORDERINGS = {
    "largest": lambda rows: sorted(rows, key=_amount_key, reverse=True),
    "smallest": lambda rows: sorted(rows, key=_amount_key),
    "oldest": lambda rows: sorted(rows, key=lambda r: r["date_sort"]),
    "newest": lambda rows: sorted(rows, key=lambda r: r["date_sort"], reverse=True),
    "merchant": lambda rows: sorted(rows, key=lambda r: r["merchant"].lower()),
}


def unannotated(transactions, annotations, order="largest", limit=None,
                expenses_only=False):
    """Return rows that still need annotation, shaped for any front-end.

    transactions: list of Transaction
    annotations:  fingerprint -> Annotation (from store.load_existing)
    order:        one of ORDERINGS keys
    limit:        optional cap on rows returned
    expenses_only: if True, only money-out rows (the ones a tax pro itemizes)

    Each returned row is a plain dict so callers (CLI, Discord, anything)
    don't need to know the Transaction type.
    """
    rows = []
    for t in transactions:
        ann = annotations.get(t.fingerprint)
        if ann is not None and ann.filled:
            continue  # already handled by a human or a prior rule run
        if expenses_only and t.amount >= 0:
            continue
        rows.append({
            "fingerprint": t.fingerprint,
            "date": t.date,
            "date_sort": _parse_date(t.date),
            "amount": t.amount,
            "merchant": t.merchant,
            "description": t.description,
            "source_account": t.source_account,
            "source_file": t.source_file,
        })

    order_fn = ORDERINGS.get(order)
    if order_fn is None:
        raise ValueError(f"unknown order {order!r}; choices: {sorted(ORDERINGS)}")
    rows = order_fn(rows)
    if limit is not None:
        rows = rows[:limit]
    return rows


def _parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%m/%d/%Y")
    except ValueError:
        return datetime.max
