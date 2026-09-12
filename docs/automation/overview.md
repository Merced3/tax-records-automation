# Automation overview

## Thesis

The official statement is evidence. Parsed transactions are a reconstruction.
Human explanations are decisions. Exports are disposable views.

The project keeps those four things separate so an automation can be rerun
without destroying the only irreplaceable work: the source records and the
human's judgment.

## The pipeline

```text
records (official evidence)
  -> ingestion plugins (Chase PDF, Cash App PDF)
  -> independent audit checks
  -> canonical transactions with unique IDs and source locations
  -> annotations (suggestions separate from human decisions)
  -> output/raw + output/tax-professional-draft + manifests
  -> output/final only after every row is human-reviewed
  -> Google Sheets later, initially read-only/diff-only
```

## Current guarantees

- Every discovered file is parsed, explicitly ignored with a reason, or
  reported as an error. Venmo CSVs and Chase credit-card PDFs are parsed
  (2026-09); supporting notes remain explicit ignores.
- Every Chase statement reconciles to its printed balance change, every row
  follows the running-balance chain, and every date lies in its statement.
- Cash App reconciles per month, not merely at year level.
- Venmo exports reconcile beginning-to-ending balance, and parsed provider row
  IDs match the file's own IDs.
- Coverage is measured from printed statement periods, so a statement that was
  never supplied is reported instead of passing silently.
- Rules carry amount direction, and `rules-lint` reports conflicts, dead rules,
  mixed-sign winners, and rows nothing decides.
- Lookalike transactions have separate stable transaction IDs. A content
  fingerprint is retained only for comparison/deduplication.
- Annotation rewrites create a snapshot, write a temporary file, validate it,
  and atomically replace the current file.
- Rule suggestions live in separate columns. Rules can change without
  overwriting Category, Tax Treatment, or Note.
- Generated output includes a raw CSV and a manifest containing source hashes,
  parser identities, audit results, row count, Git commit, and output hashes.

## What is not claimed

- Merchant cleanup is a convenience, not proof.
- A merchant category does not establish tax deductibility.
- Passing audits do not prove complete historical coverage. They prove the
  supplied records were extracted faithfully. Coverage and known-missing
  history are reported separately and honestly.
- A rule matching a row is not evidence the match was correct.
- A PDF parser plus a reconciliation audit is strong evidence of faithful
  extraction, but the official PDF remains authoritative.
- The fourth professional column is currently configured as the human `Note`.
  Confirm that mapping with the tax professional before final export.

## Reading order for a fresh session

1. This overview
2. `how-it-works.md` — data flow and ownership
3. `auditing.md` — what is and is not proven
4. `rules.md` — year-aware suggestions versus human decisions
5. `recovery.md` — snapshots, journal, atomic writes, network failures
6. `testing.md` — why each regression exists
7. `decisions.md` — current architectural commitments
8. `future.md` — Sheets, Plaid-style sources, and interfaces
9. `setup.md` — commands
10. `context-evidence.md` — future evidence-adapter contract (not implemented)
11. `session-2026-09-rules-expansion.md` — handover: credit card & Venmo ingestion, regex rules, year-quirks, and the classification workflow

## Next boundaries

Bank APIs, Discord, and Google Sheets must reuse the core pipeline rather than
owning financial logic. A network source downloads to staging, validates and
hashes content, then commits locally; a connection failure never replaces good
local state. A UI proposes or records decisions through transaction IDs.
