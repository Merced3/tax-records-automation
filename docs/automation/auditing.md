# Auditing and evidence

## What the audit is testing

Treat ingestion as a black box: the parser claims it found transactions; the
audit compares that claim with information printed elsewhere in the official
statement. Tests protect known implementation failures; audits challenge real
private records. Both are necessary.

## Chase checks

For every statement/account:

1. Statement periods are ordered and do not overlap unexpectedly.
2. Sum of parsed transactions equals ending balance minus beginning balance.
3. Every transaction date lies inside the printed statement period.
4. Every running balance equals the prior balance plus that row's amount.
5. Empty parses are accepted only when the printed balance change is zero.

The running-balance check is per-row and catches omissions, merges, splits, or
reordering that a year total could hide.

## Cash App checks

Each month is checked independently:

1. Parsed Money In equals the month's printed Money In.
2. Parsed Money Out equals the month's printed Money Out after separating
   payments funded directly by a linked bank.
3. Every transaction date lies inside that statement month.
4. An absent Money In/Out summary is accepted as empty only when the printed
   monthly change is zero.

Monthly checks prevent one month's error from cancelling another month's error.

## Venmo checks

Venmo CSV exports print no Money In/Out summary, but they do print beginning
and ending balances and, per row, the funding source and destination. That
supports a real arithmetic relationship, re-derived from the file rather than
from parser output:

    ending = beginning + money into the Venmo balance
                       + money out funded by the Venmo balance

Card-funded payments never touch the balance and must be excluded. The audit
also compares parsed provider row IDs against the file's own IDs, so a dropped
or duplicated row cannot hide behind a matching count.

## Coverage is a separate question from correctness

`python run.py coverage <year>` measures which days of the year are covered by
printed statement periods. It exists because reconciliation cannot detect an
absent statement: every collected statement can reconcile to its own printed
balances while an entire cycle is missing. Running it on real records found a
missing 33-day Chase cycle that every arithmetic check had passed.

Rules:

- Periods come from statement contents; filenames are never used.
- Statement cycles cross calendar years, so the previous/next year's folders
  are scanned for evidence; a January statement covers prior-December days.
- Sources that print no period (Venmo) report day coverage as *unmeasurable*,
  not as gaps. "No rows that week" is not "records missing that week".
- Known-unavailable history is declared in `config/app.yaml`
  (`known_coverage_gaps`) with a reason, so it is disclosed rather than
  silently absent.
- A year is reported complete only when every measurable account covers the
  whole year and nothing is declared missing or unmeasurable. Empty discovery
  is never success.

## Rule lint

`python run.py rules-lint <year>` challenges the classification layer instead
of the parser. It reports rows matched by several rules with different
suggestions, rules that match rows but never win (dead policy), rules whose
winning rows mix income and expenses, and rows no rule and no human decides.
A matching rule is not evidence the match was correct.

## Source accounting

The audit reports parsed statements, unclaimed PDFs, ingestion errors, and every
ignored non-PDF file. Ignored is a declared policy state, not invisibility.

## Raw proof package

`python run.py build <year>` writes:

- source-level raw CSV with account, statement, balance/fee, and source location
- four-column tax-professional draft
- manifest with source SHA-256 hashes, parser names, statement IDs, transaction
  counts, ignored files, audit details, output hashes, and Git commit

The manifest shows exactly which evidence and code produced an export. The PDF
remains authoritative; the package makes the derivation reproducible.

## Limits

The parser and audit both rely on PDF text extraction, so they are not fully
independent of the PDF library. The independent summary/running-balance
relationships substantially reduce that risk. Synthetic regression tests cover
every PDF failure found so far. Merchant naming and tax meaning remain human
judgments.

Passing audits prove extraction fidelity for the records that are present.
They do not prove complete historical account coverage, correct merchant
identification, business purpose, or tax deductibility. Coverage reporting and
rule lint exist because those are separate, independently falsifiable claims.
