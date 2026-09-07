# Taxes

Personal tax-record organization, with a growing set of automation tools.

This repo serves two audiences:

- **My tax professional** — human-readable yearly records and summaries live in
  [`docs/tax-professional/`](docs/tax-professional/). The documents themselves
  (bank statements, 1099s, IRS transcripts) live in `records/`, which is
  **not committed to git** for privacy.
- **Automation** — Python tooling that reads bank statement PDFs and produces
  per-year CSVs of transactions, ready to paste into a Google Sheet. See
  [`docs/automation/overview.md`](docs/automation/overview.md) first.

## Quick start

```bash
# from the repo root, with the virtualenv set up (see docs/automation/setup.md)
.venv/Scripts/python tools/main.py verify-year 2023   # read-only, writes nothing
.venv/Scripts/python tools/main.py run                # writes CSVs to output/
```

## Layout

| Path | What it is | Committed? |
|---|---|---|
| `records/` | Financial documents, organized by year | ❌ private |
| `output/` | Generated CSVs | ❌ contains financial data |
| `tools/` | The automation code | ✅ |
| `docs/automation/` | How and why the automation works | ✅ |
| `docs/tax-professional/` | Notes written for a human tax pro | ✅ |
