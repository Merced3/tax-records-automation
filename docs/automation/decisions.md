# Architecture decision record

This file records current decisions and why they exist. Previous wording and
superseded experiments remain available in Git history; this document describes
the system as it works now.

## 0001 — Official records are immutable evidence

`records/` is private and never rewritten by automation. PDF statements remain
authoritative even if a future Plaid-style source provides cleaner structured
transactions. Derived data must point back to source file, page, line, and hash.

## 0002 — Evidence, decisions, and exports are separate

- `records/`: evidence that cannot be regenerated
- `annotations/`: human decisions that cannot be regenerated
- `output/`: generated views that can be rebuilt
- `backups/`: recovery snapshots, baseline, and journal

Annotations do not belong under output merely because the application created
the initial rows. Human edits change their ownership and durability.

## 0003 — Plugins isolate institution-specific ingestion

Chase and Cash App parsers implement one interface and emit canonical
statements/transactions. Core auditing, annotation, output, Discord, Sheets, and
future API sources must not contain Chase/Cash-App parsing knowledge.

## 0004 — Transaction identity and comparison fingerprints are different

A content fingerprint answers "do these rows look alike?" It is not unique.
A Transaction ID answers "which exact source row is this?" and incorporates
statement identity, source values, running balance where available, and an
occurrence number. Exact repeated charges stay separately annotatable.

This supersedes the original fingerprint-as-primary-key design, which collapsed
legitimate duplicate charges.

## 0005 — Audit real relationships, test known failures

Real-record auditing treats ingestion as a black box and compares it with
statement summaries, periods, and running balances. Synthetic regression tests
encode only meaningful contracts and failures actually observed. Neither
replaces the other.

Output and annotation rewrites are refused when real-record audits fail.

## 0006 — Every discovered source receives a disposition

A file is parsed, unclaimed, errored, or explicitly ignored with a reason.
Non-PDF files cannot remain invisible merely because no plugin claims them;
unclaimed structured files are reported as explicit ignores, not skipped.

## 0007 — Human decisions and rule suggestions use separate columns

Rules write Suggested Category/Note plus Rule ID/Version. Humans write Category,
Tax Treatment, and Note. Rules can be refreshed as often as needed and never
overwrite human fields. Suggestions remain in `need-you` until reviewed.

Legacy 2022 data was migrated conservatively: existing non-rule text became
human state; other years were regenerated because the user confirmed only 2022
contained hand-written work.

## 0008 — Rules are year-aware policy data, not tax conclusions

Private rules have stable IDs, versions, and optional year/institution/account
scope. They suggest merchant classification. Merchant identity alone does not
prove business purpose or deductibility; Tax Treatment and Note require a human.

Real rules are private at `config/rules.yaml`. Only a sanitized example is
committed publicly.

## 0009 — Durable state uses snapshot + atomic replacement + journal

Before replacing an existing file, create a timestamped snapshot. Write and
fsync a temporary file, validate it, then atomically replace the destination.
A private baseline detects external human-column edits on the next refresh and
records them in an append-only journal.

This pattern also governs future network ingestion: stage, validate, hash,
journal, then commit. Wi-Fi loss must preserve the last accepted state.

## 0010 — Output has raw, draft, final, and manifest layers

`output/raw` preserves all available source-level fields and provenance.
`output/tax-professional-draft` maps canonical transactions and annotations to
the professional's four columns. `output/final` is blocked until every row is
human-reviewed and the audit passes. A manifest hashes sources/outputs and
records audit results, parser identity, row counts, ignored files, and Git
commit.

The configured fourth-column mapping is currently human `Note`; it must be
confirmed with the tax professional before final use.

## 0011 — The work queue is reusable by any interface

`need-you` selection and ordering are pure logic. CLI, Discord, TUI, or web UI
may render it differently but must use Transaction IDs and the same annotation
service. Interfaces may approve, override, defer, or explain; they do not parse
statements or decide tax treatment.

## 0012 — Public repository uses private runtime configuration

Transaction data, annotations, backups, outputs, professional notes, and actual
rules are ignored. `config/rules.example.yaml` and
`docs/tax-professional.example.md` document shapes without publishing new
personal details. Previously published history is accepted by the owner, but no
new private operational data should enter commits.

## Accepted limitations

- Merchant cleanup is best-effort and human-reviewed.
- PDF parser and audit both depend on PDF text extraction; independent statement
  arithmetic and synthetic regressions reduce but cannot make that risk zero.
- Venmo monthly CSV exports are ingested by a dedicated plugin (since
  2026-09); its audit is row-completeness + date-span because the exports
  carry no printed totals.
- A network bank-data source, Discord interface, and Google Sheets integration
  are future adapters, not core logic.
