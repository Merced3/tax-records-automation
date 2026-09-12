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

`tests/test_correctness.py` holds the correctness-work failure tests. Each one
asserts that a *wrong* outcome is caught, not that a happy path works:

- an income rule must not claim same-merchant purchases (the DoorDash collision)
- an unquoted comma in a YAML flow mapping is a load error, not a short needle
- an invalid `amount_sign` is a load error
- lint detects conflicts, fully shadowed rules, mixed-sign winners, and rows
  nothing decides; a human-reviewed row is not "unmatched"
- a malformed Venmo amount raises instead of silently becoming 0.00
- non-moving Venmo statuses are counted, not silently dropped
- Venmo identity survives moving/renaming the export, and duplicate provider
  IDs are an error
- the Venmo balance-chain audit fails when a card-funded payment is wrongly
  treated as balance-funded
- human text follows a changed Transaction ID, and the safety stop still aborts
  (leaving the file byte-identical) when a human row cannot be matched
- coverage finds a missing middle statement that every arithmetic check passes
- empty discovery is not complete coverage
- a January statement covers prior-December days
- declared known-missing history keeps the year incomplete
- a derived (unprinted) period reports "unmeasurable", never fabricated gaps
- a human override beats an approved rule, and a handwritten note coexists with
  a rule-supplied category
- an unapproved suggestion is not a decision and never reaches the export
- a version bump makes an approval stale; an unapproved year is not "stale"
- a category without a note is not deliverable; Tax Treatment stays optional
- approving a rule empties the row queue it covers (no redundant approvals)
- a prior-December row on a January statement lands in the correct tax year
- the same transaction appearing in two statement years is refused
- a dirty working tree is recorded as not reproducible from its commit
- changed code changes the manifest's code hash
- `final` refuses on unresolved rows, incomplete coverage, or missing resolution

A failure test is only trusted after the fix is temporarily reverted and the
test is observed to fail. Tests that cannot fail prove nothing.

The private `audit`, `coverage`, and `rules-lint` commands are the integration
checks against real records. The
public tests use synthetic statement text so no financial information enters
Git. Tests prevent known regressions; audits detect unknown inconsistencies in
real evidence.
