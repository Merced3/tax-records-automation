# Tax Records Automation

A private-first pipeline that turns official bank statements into auditable
transaction records, preserves human explanations, and prepares controlled
four-column drafts for a tax professional.

The repository is public. Financial records, annotation files, real rules,
backups, generated outputs, and tax-professional notes are private and ignored
by Git.

## Start here

1. Read [`docs/automation/overview.md`](docs/automation/overview.md).
2. Install: `.venv/Scripts/pip install -e .`
3. Audit: `python run.py audit 2022`
4. Refresh annotations safely: `python run.py annotate 2022`
5. See rows needing a human: `python run.py need-you 2022`
6. Build raw evidence and a professional draft: `python run.py build 2022`

A final export is deliberately blocked until every row has human review and
the audit passes. Google Sheets writing is not implemented yet.

## Data boundaries

| Path | Meaning | Git |
|---|---|---|
| `records/` | Original evidence; never rewritten | ignored |
| `annotations/` | Durable human decisions and rule suggestions | ignored |
| `output/` | Rebuildable raw/draft/final exports and manifests | ignored |
| `backups/` | Automatic snapshots, baseline state, and journal | ignored |
| `config/rules.yaml` | Real year-aware rules | ignored |
| `config/rules.example.yaml` | Sanitized public example | tracked |
| `src/financial_automation/` | Application code | tracked |
| `tests/` | Small regression suite for real failures | tracked |
