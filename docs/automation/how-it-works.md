# How it works

## 1. Discovery accounts for every file

The pipeline scans `records/<year>/Bank Statements/`. PDFs are offered to
registered ingestion plugins. Other files are not invisible: they appear as
explicit ignores with a reason. Venmo monthly CSV exports are parsed by a
dedicated plugin; Chase credit-card PDFs likewise. CSVs no plugin claims,
and non-PDF/non-CSV files, remain explicit ignores with a reason.

## 2. Plugins produce one canonical shape

Each bank-specific plugin returns a statement period and transactions. Every
transaction includes:

- unique Transaction ID
- lookalike/content fingerprint
- institution and account
- stable statement identity
- date, amount, raw bank description, cleaned merchant
- running balance or fee when available
- source file, page, and extracted line

The Transaction ID includes statement identity, source values, running balance
where available, and an occurrence number. Two identical-looking charges can
therefore remain two independently annotatable rows.

When a source supplies its own row ID (Venmo), identity is derived from that
provider ID instead, so moving, renaming, or re-exporting a file does not
change Transaction IDs. Statement identity for such sources is content-derived
(period plus row IDs), never path-derived.

Each statement also records whether its period was `printed` in the source or
`derived` from the rows present. Coverage reporting depends on that difference.

## 3. The audit challenges the parser

The audit reads statement summaries independently and compares them with parser
results. Output is refused when an audit fails.

Chase checks sequence, statement totals, every date, every running-balance step,
and genuinely empty statements. Cash App checks each monthly statement's Money
In/Out and dates, accounting separately for bank-funded payments. Venmo checks
the beginning-to-ending balance chain (excluding card-funded payments, which
never touch the balance) and matches parsed provider IDs to the file's IDs.

The audit cannot detect a statement that was never supplied. That is what
`coverage` is for: it measures covered days from printed statement periods and
reports gaps and declared known-missing history separately.

## 4. Suggestions and decisions are different

`config/rules.yaml` creates `Suggested Category` and `Suggested Note`. It never
writes Category, Tax Treatment, or Note. Those three columns are human-owned.
Changing a rule updates suggestions while preserving human decisions.

Rules have an ID, version, optional applicable years/institutions/accounts and
amount direction, a match, and a suggestion. This makes rules explainable,
year-aware, and direction-aware. `rules-lint` reports conflicts, dead rules,
mixed-sign winners, and undecided rows.

## 5. Annotation writes are transactional

Before rewriting an existing annotation CSV, the program snapshots it under
`backups/`. It writes the replacement beside the original, flushes it to disk,
reads it back to validate the header and row count, then uses an atomic replace.
If a human-annotated legacy row cannot be matched, the operation stops and the
current file remains intact.

Identity-scheme migrations (such as Venmo adopting provider row IDs) change
Transaction IDs for unchanged source rows. Rows whose old ID no longer exists
are therefore re-matched by financial content (date, amount, raw description),
so human text follows its transaction instead of being orphaned — and is never
copied onto a second row. `python tools/verify_human_preservation.py
backups/<snapshot>` proves afterwards that every human-typed value survived.

A private baseline lets the next run detect Category/Tax Treatment/Note edits
made in Excel or VS Code and append those changes to `backups/journal.jsonl`.

## 6. Output has layers

- `output/raw/<year>.csv`: all available source-level fields and provenance.
- `output/tax-professional-draft/<year>.csv`: exactly four configured columns.
- `output/final/<year>.csv`: refused until all rows are human-reviewed and the
  audit passes.
- A manifest beside each professional output hashes both source files and
  generated files, records the audit, ignored sources, row count, and Git commit.

`annotations/` is not inside `output/` because it contains irreplaceable human
state. Everything in `output/` is safe to rebuild.
