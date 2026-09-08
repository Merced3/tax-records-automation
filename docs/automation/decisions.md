# Decision log (ADRs)

Every "we chose X over Y, because Z" lives here so future sessions don't
re-litigate settled questions. Newest at the bottom. Don't rewrite history —
supersede old decisions with new entries.

---

## 0001: CSV first, Sheets API later

**Decision:** Output is CSV files in `output/` (gitignored). A Google Sheets
writer comes later, consuming the same transaction data.

**Why:** Trust must be earned before automation touches the real
spreadsheet, which already contains hand-annotated work. CSVs are eyeball-able
and zero-risk. The Sheets API supports submitting an entire table in one
request, so the future writer is a small addition, not a rewrite — the CSV
phase is not throwaway work.

---

## 0002: Plugin architecture for parsers

**Decision:** Bank-specific reading logic lives in one file per bank under
`tools/parsers/`. The engine routes PDFs to whichever plugin claims them and
contains zero bank-specific code.

**Why:** Banks will change (the user has said as much). The cost of a new
bank should be exactly one new file. This also makes the Cash App stub
harmless: unclaimed PDFs are reported, never silently dropped.

---

## 0003: Exactly the tax professional's 4 columns — but columns are config

**Decision:** CSVs contain `Amount, Date, Merchant, Bank Description` and
nothing else. Column names and order come from `config.yaml`; the writer
*can* emit extra columns (Account, Source File, Fingerprint) but they're off
by default.

**Why:** The tax pro's downstream systems expect the 4-column format and he
charges per filing, so his workflow is not ours to disrupt. At the same time,
we don't want a format change to ever require a code change.

---

## 0004: Include all transactions by default

**Decision:** Default `include: all` — income and expenses both go in.

**Why:** We don't know what the tax professional doesn't want to see, and
excluding data is a one-way door. If he later asks for expenses only, it's a
one-word config change (`include: expenses`), implemented in
`pipeline/filters.py`.

---

## 0005: Sensitive data never enters git

**Decision:** `records/` (the PDFs), `output/` (generated CSVs), and `.venv/`
are gitignored. The repo is intended to be public.

**Why:** The PDFs contain full name, address, and partial account numbers.
Generated CSVs contain complete transaction histories. One `.gitignore` line
per folder is the simplest reliable barrier. Rule: never `git add -f`
anything under those paths. Audit `git status` before every push.

---

## 0006: Code lives in `tools/`, docs split by audience

**Decision:** `tools/` holds all automation code; `docs/automation/` for the
machinery, `docs/tax-professional/` for human-tax-pro material; a flat
repo-facing `README.md` at the root.

**Why:** A stranger (or a fresh AI session) should be able to read the root
README and immediately know where things live. The tax-pro docs predate the
automation and serve a different reader; merging them would serve neither.

---

---

## 0007: Reconciliation audit over unit tests

**Decision:** Correctness is proven by reconciling parsed transactions
against the summaries each statement prints about itself (`main.py audit`),
not by a conventional unit-test suite.

**Why:** The statements are the ground truth. A unit test can only assert
what we already believe the PDF says; the reconciliation check asserts what
the *bank* says happened, in dollars and cents. It caught two real things on
its first run that no amount of eyeballing had: a duplicated statement file
in 2024, and the fact that Cash App's bank-funded payments never touch the
Cash App balance. When the audit passes, "is the output accurate?" has a
provable answer. See `docs/automation/auditing.md` Level 4.

---

---

## 0008: Annotations are local input files; the sheet is a pure output

**Decision:** The "why" behind each expense (what the tax pro needs for
write-offs) is captured in `annotations/<year>.csv` files the pipeline
generates and the human fills in — NOT typed directly into the Google Sheet.

**Why:** Human judgment is a first-class *input* and must live in files we
own: durable, re-runnable, and safe from any sheet rebuild. The Google Sheet
becomes a *view* of (transactions + annotations), never the place work
happens. Each annotation row carries the transaction's fingerprint, so
re-running `annotate` re-associates human work with the right transaction
even after re-parsing or re-sorting — and never overwrites a filled row.
This also defers the Sheets writer until the sheet's final shape
(transactions + annotations merged) is known, so we build it once.

**Consequence:** `annotations/` is gitignored like `records/` and `output/` —
it contains financial judgments about real transactions.

---

---

## 0009: Dollar reconciliation per statement; dedupe only across files

**Decision:** The Chase audit must reconcile *dollars*, not just statement
chaining: each statement's parsed transaction sum must equal its own printed
balance delta. And dedupe must only remove a charge when it appears in TWO
different statements (overlap) — never collapse identical charges within one
statement.

**Why (this was earned, not theorized):** A user spot-check found missing
transactions, which exposed THREE compounding bugs the date-chaining audit
had silently allowed — 868 missing transactions (18% of all data):

1. **Marker-format bug:** newer statements use `*start*transactiondetail`
   (no spaces) vs the old spaced form → whole files read as 0 transactions
   while reporting "parsed successfully."
2. **Page-boundary fusion:** at page breaks, the text layer fuses the
   `*end*` marker + footer + the page's last transaction into one mangled
   line (`*end*transac1tion detail0/31 Zelle Payment...`), silently dropping
   that transaction and corrupting its date. 53 such lines across 33 files.
3. **Dedupe false-positives:** identical same-statement charges (a
   double-billed gym membership) share a fingerprint and were being dropped
   as "duplicates." Investigating revealed statements never actually overlap
   in content — every prior "duplicates removed" count was this bug.

The lesson baked into the audit: **chaining/dates prove structure, only
dollars prove extraction.** Any future parser change must keep the
balance-delta check green.

---

## Known technical debt (accepted, not forgotten)

- **Year stamping.** Transaction dates come from MM/DD on the statement and
  inherit the folder's year. Statements straddling New Year will mislabel a
  handful of early-January transactions. Proper fix: parse the statement
  period header ("March 09, 2023 through April 10, 2023") and infer each
  transaction's year from it. Deliberately deferred — baby steps.
- **2026 is excluded from config for now.** Its Cash App folder is empty
  (no statements yet). Add `2026` to `years:` in `tools/config.yaml` when
  statements exist.
- **Merchant cleanup is naive.** Regex stripping, not entity resolution.
  Acceptable because the raw description column is always preserved and a
  human reviews the Merchant column anyway.
- ~~**2024 duplicate count (98)**~~ RESOLVED by the audit (0007): a
  misnamed duplicate `Jun-10.pdf` duplicated the `May-8.pdf` statement.
  Deleted; 2024 now dedupes a normal 4 overlaps.
