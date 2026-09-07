# Overview — read this first

## The problem

Tax years 2022–2025 need to be reconstructed for filing. The raw evidence is
a folder of bank statement PDFs (~145 of them, Chase and Cash App, 2022–2025).
Getting every transaction into a spreadsheet by hand takes forever and is
error-prone.

## What this system does

It reads the bank statement PDFs, extracts every transaction (date, amount,
description), removes duplicates, and writes **one CSV per year** into
`output/`. Those CSVs match the exact 4-column format my tax professional
asked for (`Amount, Date, Merchant, Bank Description`), so they can be pasted
straight into the Google Sheet `Merced-Bank-Statement-Organization`
(one tab per year).

## Why CSVs instead of writing to Google Sheets directly?

Two reasons:

1. **Trust before automation.** A CSV can be opened and eyeballed before
   anything touches the real spreadsheet. The spreadsheet contains
   hand-annotated work we must never clobber.
2. **The CSV is not a detour.** When we later add a Google Sheets "writer",
   it will consume the exact same data the CSV writer consumes. The Sheets
   API can submit a whole table in one request, so the future API mode is a
   small addition — not a rewrite. This is recorded as
   [decision 0001](decisions.md#0001-csv-first-sheets-api-later).

## The design philosophy in one paragraph

The system is a pipeline with three seams: **parsers** (how we read a
specific bank's PDF), the **engine** (bank-agnostic machinery that finds
PDFs, routes them to the right parser, dedupes, sorts), and **writers**
(where results go). Every choice that might change — which years, which
columns, whether to include income or only expenses — lives in
`tools/config.yaml`, not in code. The bet: banks change, spreadsheets change,
tax-pro preferences change; the pipeline shape shouldn't have to.

## Current status

- Chase checking/savings statements: **working** (128/128 parsed cleanly).
- Cash App statements: **working** (17/17 parsed cleanly; zero-transaction
  months correctly produce zero rows).
- All 145 statement PDFs currently parse — zero unclaimed, zero errors.
- Reconciliation audit (Level 4) proves extraction per year.
- Annotation workflow: `annotate` generates per-year files you fill in
  (Category/Note); re-running preserves your work. See decision 0008.
- Google Sheets writer: not started — deferred until annotations define the
  sheet's final shape (decision 0008), so it's built once.

## Where to go next

- `how-it-works.md` — the pipeline story in plain language
- `decisions.md` — every "we chose X over Y" and why
- `auditing.md` — how to convince yourself the output is correct
- `setup.md` — how to actually run the thing
