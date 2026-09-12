# Handover: correctness work and remaining blockers

This session implemented the corrective work agreed after the rules-expansion
handover. It does **not** claim the deliverable is finished. Read the
"Remaining blockers" section before telling anyone the exports are ready.

Commits: docs checkpoint, then one commit per bounded stage, then a
sanitization commit. Each stage kept the real-record audits passing.

## What changed

### Amount-direction rules and validation

`applies.amount_sign` (`positive` / `negative`) restricts a rule to money-in or
money-out rows. Unknown `match`/`applies` keys and invalid `amount_sign` values
are now load errors.

This fixed a silent, real mislabeling: a needle written as a YAML flow mapping
with an unquoted comma (`{contains: example co, inc.}`) parsed as **two keys**
and shortened the needle, so a gig platform's payout rule also matched
purchases made through that platform. Three private income rules were affected;
they are corrected, quoted, version-bumped, and scoped to `positive`.

### Rule lint

`rules-lint <year>` reports multi-rule conflicts, fully shadowed (dead) rules,
rules whose winning rows mix signs, and rows nothing decides. It reports rather
than auto-corrects, because refunds legitimately reverse direction.

### Strict Venmo parsing, provider identity, real audit

- Malformed amounts/fees raise instead of silently becoming `0.00`.
- Identity comes from Venmo's own row ID, so moving/renaming an export no
  longer changes Transaction IDs; statement IDs are content-derived.
- `Issued` standard transfers are kept (they move money). Other statuses are
  counted and reported, not silently dropped.
- The audit re-derives `ending = beginning + balance-affecting rows` from the
  file itself and compares parsed IDs with the file's IDs. All 31 exports
  reconcile. The previous "row count" check was much weaker than claimed.

### Coverage reporting

`coverage <year>` measures covered days from **printed** statement periods
(never filenames), consulting adjacent years because cycles cross year
boundaries. Sources printing no period report coverage as *unmeasurable*
instead of fabricating gaps. Known-unavailable history is declared privately in
`config/coverage-gaps.yaml`; if that file is absent, a warning says so.

This found a real missing statement that every arithmetic audit passed, plus a
`Credit Card` / `Credit Cards` folder-naming variance across years. Both are
recorded in the private `records/2024/Bank Statements/COVERAGE-NOTES.txt`.

### Rule approval and field-level resolution

Category and Note resolve independently: human override, then (future) eligible
context evidence, then owner-approved rule. Approval is per rule **and
version**, stored in `annotations/rule-approvals.yaml`, written only by
`approve-rule`. A version bump marks an approval stale; an unapproved year is
unapproved, not stale. Unapproved suggestions are never exported as values, and
rule text is never relabeled as human-typed.

### Calendar-year exports

`calendar-year <year>` audits every contributing statement year, then regroups
accepted rows by transaction date, refusing duplicate Transaction IDs. Records
and annotations are untouched. `tools/reconcile_exports.py` proved conservation
for all four years (2022 draws 80 rows from the 2023 folder, 2023 draws 73 from
2024, 2024 draws 82 from 2025).

### Provenance and gates

Manifests hash the code, config, private rules, approvals, and annotations that
actually ran, record per-field decision sources, coverage, and approvals, and
mark a dirty tree `reproducible_from_commit: false`. `final` refuses on
unresolved rows, failed audits, or incomplete coverage.

## Verification actually performed

- 55 tests pass. Failure tests were validated by reverting each fix and
  observing the tests fail; a test that cannot fail proves nothing.
- Real-record audits pass for 2022-2025.
- Human-text preservation proved twice against pre-change snapshots: 184/184
  human rows intact (`tools/verify_human_preservation.py`).
- Export conservation: CONSERVED for all four years.
- Migration behaviour was tested on synthetic rows only, never against live
  human annotations.

## Remaining blockers (why this is not done)

1. **Almost nothing is approved yet.** Deliverable rows (both Category and
   Note): 73/863 (2022), 7/1579 (2023), 5/1829 (2024), 4/1759 (2025). Rules
   awaiting owner approval: 109 / 189 / 228 / 196. These are rule decisions, not
   thousands of row decisions, but they are still the owner's to make.
2. **622 rows have no note from any source**, only a suggested category. Each
   needs a note or a rule that supplies one.
3. **Rule lint is not clean.** Conflicts (23/140/136/114), shadowed rules, and
   mixed-sign winners remain. Most conflicts are intentional
   specific-before-general ordering, but they have not been reviewed one by one,
   and mixed-sign rules may still be mislabeling refunds as income.
4. **Coverage is incomplete for every year.** 2022 is missing roughly five
   months of one institution plus the declared unavailable account; 2024 is
   missing one statement cycle; 2023/2025 have a declared gap or year-edge days.
   `final` therefore refuses, correctly.
5. **The fourth professional column mapping is still unconfirmed** with the tax
   professional.
6. **Account-name variance** (`Credit Card` vs `Credit Cards`) must be resolved
   before any account-scoped rule is trusted.

## What passing checks do and do not prove

Audits prove the supplied records were extracted faithfully. They do not prove
complete historical coverage, correct merchant identification, business
purpose, or tax deductibility. Coverage proves which days statements cover; it
cannot discover an account never mentioned. A matching rule is not evidence the
match was correct, and an approved rule is a classification decision, not a
tax conclusion.

## Not implemented, deliberately

Discord retrieval, timeline/LLM inference, Plaid ingestion, and Google Sheets
writes. `context-evidence.md` holds the future evidence contract; context may
outrank a generic rule only under an explicit eligibility policy, and never
outranks a human override.
