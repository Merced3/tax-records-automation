# Testing policy

Tests are intentionally few and evidence-driven. A test is added when it
protects a meaningful contract or a failure that actually occurred. Trivial
getters, library behavior, and implementation trivia are not tested.

Run:

```powershell
python -m unittest discover -s tests -v
```

Current regression contracts cover:

- spaced and unspaced Chase markers
- fused page-ending dates beginning with 0 and 1
- December-to-January year assignment
- identical-looking same-statement transactions receiving unique IDs
- cross-statement deduplication preserving same-statement repeats
- wrapped descriptions being finalized before identity generation
- Cash App linked-bank-funded payments
- empty statements
- year-specific rules
- atomic annotation rewrite, backup, and human-text preservation

The private `audit` command is the integration check against real records. The
public tests use synthetic statement text so no financial information enters
Git. Tests prevent known regressions; audits detect unknown inconsistencies in
real evidence.
