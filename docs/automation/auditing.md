# Auditing — how to trust the output

The question this document answers: *"If I'm suspicious that the output is
wrong, how do I check?"* — ordered from "free, already built" to "future work".

## Level 0: Read the run report (built, free)

Every `run` / `verify-year` prints a report. Healthy signs:

- **unclaimed PDFs: 0.** Any unclaimed file means a statement format
  changed (or a new bank appeared) and its data is *missing from the CSV* —
  this is the most important number in the report.
- **errors: 0.** An error means a parser choked on a file it claimed.
- **duplicates removed: small.** Overlapping statements make some duplicates
  normal (2022: 3, 2023: 8). A big number (2024: 98) isn't proof of a
  problem — but it's a prompt to spot-check.

## Level 1: Eyeball one statement (built, free)

```bash
.venv/Scripts/python tools/main.py verify 2023 "Chase/Everyday Spend Bank Account/Apr-10.pdf"
```

Prints every transaction extracted from that single PDF, writes nothing.
Open the actual PDF side by side and compare a page. Five minutes buys real
confidence. This is the right move after any parser code change.

## Level 2: Coverage check (built, manual)

A year should have ~12 statements per account. `verify-year` tells you how
many statements parsed; the records folder tells you how many exist. If
2024 shows 36 parsed + 5 unclaimed = 41 PDFs and the folder holds 41, nothing
was skipped.

## Level 3: Spot-check a random row (built, manual)

Pick any row in a CSV. The `Source File` and `Fingerprint` columns (enable
them temporarily in `config.yaml`) tell you exactly which PDF it came from.
Open that PDF, Ctrl+F the amount. If it matches, that row is provably real.

## Level 4: Reconciliation against the statement's own math (BUILT)

```bash
.venv/Scripts/python tools/main.py audit 2024
```

Each statement prints its own summary, so we can *prove* extraction rather
than eyeball it:

- **Chase** — five proofs. (1) Per account, statements chain into
  consecutive periods (catches duplicate/missing statement files).
  (2) **Each statement's parsed sum equals its printed balance delta, to
  the cent** (catches dropped/fused transactions — decision 0009).
  (3) **Every transaction date falls inside its statement's period**
  (catches right-amount-wrong-date rows).
  (4) **The running-balance chain is internally consistent** — each row's
  printed balance equals the previous balance plus its amount (catches
  merged, split, or reordered rows; the strongest per-row proof we have).
  (5) Transaction years come from the statement period, so Dec→Jan
  statements stamp December rows with the prior year (decision 0012).
- **Cash App** — the year's extracted Money In and Money Out must equal the
  statements' own printed totals, after excluding payments funded directly
  from the linked bank (which never touch the Cash App balance and are
  therefore correctly excluded from the printed totals).

This is the strongest audit we have: it turns "the parser looks right" into
"the parser is provably consistent with what the banks themselves printed."
Run it after any parser change and before trusting a year's CSV.

## Level 5: Sheet diff (future, API era)

Before the Google Sheets writer ever writes, it will fingerprint what's
already in the tab and show the diff — rows to add, rows already present.
Hand-annotated rows are never touched. Re-running becomes safe by
construction (idempotent), and "what are we missing?" is computed, not
eyeballed.

## What to do when an audit finds a problem

1. Don't patch the CSV by hand — the fix belongs in the parser or it will
   regress silently next run.
2. Add the offending statement as a `verify` case so the bug stays visible
   until fixed.
3. Note it in `decisions.md` if the fix changes a design assumption.
