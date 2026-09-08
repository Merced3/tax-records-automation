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
