# Setup and commands

## Install

From the repository root:

```powershell
.venv\Scripts\pip install -e .
```

Use `python run.py ...`. Do not invoke a `.py` file as a bare Windows command.

Copy the sanitized rules template once if no private file exists:

```powershell
Copy-Item config\rules.example.yaml config\rules.yaml
```

## Commands

```powershell
# Read-only proof against the year's statements
python run.py audit 2022

# Show one statement's parsed rows
python run.py verify 2022 "Chase/Savings Emergance Fund Bank Account/Jul.pdf"

# Safely refresh annotation state; snapshots + atomic replacement
python run.py annotate 2022

# Preview current rule suggestions without writing
python run.py annotate-dry 2022

# Which days of the year do printed statement periods actually cover?
# Reports gaps and declared known-missing history; exits honestly.
python run.py coverage 2022

# Challenge the rules: conflicts, dead rules, mixed-sign winners,
# and rows neither a rule nor a human decides. Non-zero exit if unclean.
python run.py rules-lint 2022

# Rules awaiting owner approval, ranked by how many rows each would resolve
python run.py approvals 2022

# Record the owner's decision for a recurring rule (this year, or all years)
python run.py approve-rule 2022 merchant.example
python run.py approve-rule 2022 merchant.example --all-years

# Field-level resolution status: what is deliverable and what blocks the rest
python run.py resolve 2022

# Human work queue; suggestions remain visible for approval/override
python run.py need-you 2022
python run.py need-you 2022 --order smallest --limit 50
python run.py need-you 2022 --order merchant --all

# Audit then produce raw + four-column draft + manifest
python run.py build 2022
python run.py build       # every configured year

# Derived tax-year view by transaction date; audits every contributing
# statement year first and leaves records/annotations untouched
python run.py calendar-year 2022
python run.py calendar-year 2022 --final

# Prove the regrouping lost, gained, or duplicated nothing
python tools/reconcile_exports.py 2022

# Refuses unless every row resolves Category AND Note, audit passes,
# and statement coverage is complete
python run.py final 2022

# Necessary public regression tests
python -m unittest discover -s tests -v

# After any identity/schema migration: prove human text survived
python tools/verify_human_preservation.py backups/<snapshot-dir>
```

## Annotation columns

Do not edit machine columns, Suggested columns, Rule ID, or Rule Version.
Edit only:

- `Category`: what the purchase generally is
- `Tax Treatment`: optional; business, personal, mixed, transfer, income,
  uncertain. Primarily the professional's responsibility.
- `Note`: transaction-specific explanation/business purpose

A deliverable row requires BOTH `Category` and `Note`.

A suggestion is not approval. A row leaves `need-you` when a human field
decides it **or** when the owner approves the rule that covers it — recurring
decisions are made once per rule, not once per row. Row-level human text always
outranks any rule.

## Changing rules safely

1. Edit private `config/rules.yaml`.
2. Increase the rule's `version` when its meaning changes.
3. Restrict `applies.years` when the same merchant means different things in
   different years, and `applies.amount_sign` when a name appears in both
   payouts and purchases. Quote any needle containing a comma.
4. Run `annotate-dry`.
5. Run `rules-lint` and resolve conflicts, dead rules, and mixed-sign winners.
6. Run `annotate` to refresh suggestion columns.
7. Approve or override by entering human-owned fields.

Rules no longer masquerade as human annotations and can be refreshed without
wiping prior decisions.
