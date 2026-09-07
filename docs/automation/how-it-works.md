# How it works

The plain-language story of what happens when you run the pipeline.

## The cast

| Piece | File | Its job |
|---|---|---|
| Entry point | `tools/main.py` | The only thing you run. Three commands: `verify`, `verify-year`, `run`. |
| Config | `tools/config.yaml` | Every knob: which years, which columns, include-all vs expenses-only. |
| Engine | `tools/pipeline/engine.py` | Finds PDFs, asks parsers to claim them, dedupes, sorts. Knows no bank specifics. |
| Transaction | `tools/pipeline/models.py` | The one record type everything speaks. Carries its own fingerprint + origin. |
| Parsers | `tools/parsers/*.py` | One file per bank/format. The only place bank-specific knowledge lives. |
| Writers | `tools/writers/*.py` | Turn transactions into output. CSV today, Google Sheets later. |

## The story of one `run`

1. **Discovery.** For each configured year, the engine walks
   `records/<year>/Bank Statements/` and collects every PDF.
2. **Claiming.** For each PDF, the engine reads the first page's text and
   asks each registered parser, in order: "is this yours?" The Chase parser
   claims anything containing "JPMorgan Chase Bank". If *no* parser claims
   a file, it is listed in the report as **unclaimed** — never silently
   skipped. (This is how we know the 17 Cash App PDFs are still waiting.)
3. **Parsing.** The claiming parser extracts transactions: date, signed
   amount (negative = money out), a best-effort merchant name, and the raw
   bank description. Each transaction also remembers which PDF and which
   account folder it came from.
4. **Fingerprinting & dedupe.** Every transaction gets a fingerprint from
   its date + amount + description + account. Some statements overlap
   (e.g. `Apr-10.pdf` and `Apr.pdf` cover the same days), so duplicates are
   expected; the engine keeps the first copy and counts the rest. The count
   is in the report — dedupe is transparent, not a black box.
5. **Filtering.** The `include` setting in config decides what survives:
   `all` (default — we don't presume to know what the tax pro doesn't want)
   or `expenses` (money out only).
6. **Writing.** The CSV writer produces `output/<year>.csv` with exactly the
   columns config asks for, in the order config asks for them.

## Why the seams are where they are

- **Parsers are plugins** because banks change. Switching banks someday
  means writing one new file in `parsers/`; the engine, config, and writers
  don't change.
- **Columns are config** because the spreadsheet format belongs to the tax
  professional. Today it's 4 columns; if that ever changes, it's a config
  edit. The writers already *can* emit more (Account, Source File,
  Fingerprint) — they're just off by default.
- **The transaction carries provenance** (source file, account, fingerprint)
  so that future auditing features never need to re-read a PDF to answer
  "where did this row come from?"

## Known limitations (honest list)

- **Merchant names are best-effort.** Banks mangle merchant names into
  noise; we strip the obvious junk ("Card Purchase", trailing card digits)
  but the result still needs human review. The `Bank Description` column
  always keeps the full raw text, so nothing is lost.
- **Transaction dates are MM/DD on the statement; we stamp them with the
  folder's year.** A statement period that straddles New Year (e.g.
  Dec 30–Jan 9) would mislabel a few days. Fix is planned; it's in
  decisions.md as a known debt item.
- **The 2024 run removed 98 duplicates** — more than other years. Likely
  overlapping statements downloaded twice, but it deserves a human glance
  (see auditing.md, spot-check).
