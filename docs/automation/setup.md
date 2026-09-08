# Setup

## Prerequisites

- Windows, Python 3.9 (the existing `.venv` is already created)
- Everything else installs from `requirements.txt`

## One-time setup

```bash
cd C:\Users\cedgo\Documents\Taxes
.venv\Scripts\pip install -r requirements.txt
```

(Packages: `pdfplumber` reads the PDFs' text layer — no OCR needed —
`PyYAML` reads the config, `natsort` is used by the older structure tool.)

## Daily use

From the repo root:

```bash
# Eyeball ONE statement. Writes nothing. Use liberally.
.venv/Scripts/python tools/main.py verify 2023 "Chase/Everyday Spend Bank Account/Apr-10.pdf"

# Parse a whole year, print stats + report. Writes nothing.
.venv/Scripts/python tools/main.py verify-year 2023

# Generate output/<year>.csv for every year in config.yaml.
.venv/Scripts/python tools/main.py run

# Generate/refresh the annotation file for a year (auto-fills obvious
# merchants from tools/rules.yaml, preserves your hand-edits).
.venv/Scripts/python tools/main.py annotate 2023
```

**Important:** always invoke via `python tools/main.py ...` (or
`.venv/Scripts/python tools/main.py ...`). Do NOT run `tools/main.py ...`
directly — Windows can't execute the `.py` as a bare command, and it will
silently do nothing (which looks like it worked but produced no output).

(On Windows, `PYTHONIOENCODING=utf-8` before the command avoids console
encoding errors from special characters in statement text.)

## Config knobs (`tools/config.yaml`)

| Key | Meaning | Default |
|---|---|---|
| `years` | which year folders to process | 2022–2025 |
| `columns` | CSV columns and their order | the tax pro's 4 |
| `include` | `all` or `expenses` | `all` |
| `records_root` / `output_dir` | where PDFs live / where CSVs go | `records` / `output` |

## Importing a CSV into the Google Sheet

1. Open `Merced-Bank-Statement-Organization`, go to the year's tab.
2. Click the first empty cell under the headers.
3. File → Import → Upload → select `output/<year>.csv` →
   "Append to current sheet" (or paste directly — the CSV is exactly
   4 columns in the sheet's order).
4. Verify the row count matches the run report, then fill in descriptions.

## If something breaks

Check the run report first (unclaimed files? errors?). Then see
`auditing.md`. If the report is clean but output looks wrong, run `verify`
on one affected statement and compare it against the PDF itself.
