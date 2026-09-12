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
overwrite human fields. Suggestions remain in `need-you` until decided — either
by a human field or by owner approval of the rule (ADR 0016).

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

## 0016 — An approved rule is a human decision; fields resolve individually

The owner decides at two levels: a row-specific field, or a rule for recurring
transactions. Requiring a row-level keystroke for every occurrence of an
already-decided recurring merchant is redundant, so approval is recorded per
rule and version in `annotations/rule-approvals.yaml`, written only by
`approve-rule`.

Approval is version-specific: bumping a rule's version makes its approval
stale, because the rule's meaning changed. Approval is also year-scopeable, and
a year the owner never approved is *unapproved*, not stale.

Category and Note resolve independently so a handwritten note can coexist with
a rule-supplied category. Precedence is human override, then (future) eligible
context evidence, then approved rule. Provenance per field is preserved and
reported; rule-generated text is never presented as human-typed text. An
unapproved suggestion is never exported as a value.

A deliverable row requires BOTH Category and Note. Tax Treatment is optional
and primarily the professional's responsibility.

## 0017 — Calendar-year exports are derived, never destructive

Statement organisation is preserved because statements are the unit of
reconciliation. A tax year is a different grouping of the same accepted rows,
selected by transaction date, so a January statement supplies prior-December
activity. The derived export is assembled only after every contributing
statement year passes its audit, refuses duplicate Transaction IDs, and never
edits records or moves annotation rows. `tools/reconcile_exports.py` proves row
and amount conservation between the two views.

## 0018 — A manifest must describe the state that actually ran

Recording only source hashes and a commit is misleading when the working tree
is dirty: the commit does not describe the code that ran. Manifests therefore
hash the code, config, private rules, rule approvals, and annotations actually
used, record per-field decision sources, coverage, and approvals, and mark
dirty trees `reproducible_from_commit: false`.

## 0010 — Output has raw, draft, final, and manifest layers

`output/raw` preserves all available source-level fields and provenance.
`output/tax-professional-draft` maps canonical transactions and annotations to
the professional's four columns. `output/calendar-year` holds the derived
tax-year view (ADR 0017). `output/final` is blocked until every row resolves
both Category and Note, the audit passes, and coverage is complete. A manifest hashes sources/outputs and
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

## 0013 — Rules carry amount direction, and lint is part of trusting them

`applies.amount_sign` restricts a rule to money-in or money-out rows, because a
company name appears in both its payouts and its purchases. Unknown `match`
or `applies` keys are load errors: an unquoted comma in a YAML flow mapping
silently shortened a needle and mislabeled food-delivery purchases as delivery
income, and silent acceptance is what made that possible.

A matching rule is not evidence the match was correct. `rules-lint` reports
multi-rule conflicts, fully shadowed (dead) rules, mixed-sign winners, and rows
neither a rule nor a human decides. It reports rather than auto-corrects:
refunds legitimately reverse direction, and that judgment is the owner's.

## 0014 — Identity comes from the provider when the provider supplies one

When a source prints its own stable row ID, Transaction ID is derived from it,
so moving or renaming an export cannot change identity. Statement identity for
such sources is content-derived, never path-derived.

Identity-scheme migrations must be lossless. Rows whose old ID disappeared are
re-matched by financial content so human text follows its transaction, exactly
once, and the safety stop still aborts on any unmatched human row. Preservation
is proven after the fact against a pre-change snapshot, not asserted.

## 0015 — Coverage is measured, disclosed, and separate from reconciliation

Reconciliation proves the records present were extracted faithfully. It cannot
prove they are all the records: an absent statement breaks no balance chain.
Coverage is therefore computed from printed statement periods only — never
filenames — and adjacent years are consulted because cycles cross calendar
years.

Sources that print no period report coverage as *unmeasurable* instead of
fabricating gaps from row dates. Known-unavailable history is declared in
`config/app.yaml` with a reason so it is disclosed, and a year counts as
complete only when every measurable account covers it and nothing is declared
missing. Empty discovery is never success.

## Accepted limitations

- Merchant cleanup is best-effort and human-reviewed.
- PDF parser and audit both depend on PDF text extraction; independent statement
  arithmetic and synthetic regressions reduce but cannot make that risk zero.
- Venmo monthly CSV exports are ingested by a dedicated plugin (since
  2026-09). They print no Money In/Out summary, but their beginning/ending
  balances and per-row funding sources support a real balance-chain audit.
  They print no statement period, so their day coverage is unmeasurable.
- Coverage reporting proves which days statements cover. It cannot discover an
  account the owner never mentioned and whose statements were never supplied;
  such history must be declared to be reported.
- Rule lint reports classification conflicts. Resolving them, and judging
  business purpose or deductibility, remains human work.
- A network bank-data source, Discord interface, and Google Sheets integration
  are future adapters, not core logic.
