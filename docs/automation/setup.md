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

# Human work queue; suggestions remain visible for approval/override
python run.py need-you 2022
python run.py need-you 2022 --order smallest --limit 50
python run.py need-you 2022 --order merchant --all

# Audit then produce raw + four-column draft + manifest
python run.py build 2022
python run.py build       # every configured year

# Refuses unless every row is human-reviewed and audit passes
python run.py final 2022

# Necessary public regression tests
python -m unittest discover -s tests -v
```

## Annotation columns

Do not edit machine columns, Suggested columns, Rule ID, or Rule Version.
Edit only:

- `Category`: what the purchase generally is
- `Tax Treatment`: business, personal, mixed, transfer, income, uncertain, etc.
- `Note`: transaction-specific explanation/business purpose

A suggestion is not approval. `need-you` continues to show suggested rows until
a human-owned field is filled.

## Changing rules safely

1. Edit private `config/rules.yaml`.
2. Increase the rule's `version` when its meaning changes.
3. Restrict `applies.years` when the same merchant means different things in
   different years.
4. Run `annotate-dry`.
5. Run `annotate` to refresh suggestion columns.
6. Approve or override by entering human-owned fields.

Rules no longer masquerade as human annotations and can be refreshed without
wiping prior decisions.
