# Handover: rule coverage and new ingestion sources

Historical checkpoint: `19216ae`. This handover describes what that session
built, what the owner decided, and the unresolved correctness work. It does not
assert that a matching rule makes a transaction tax-deductible or export-ready.
Private merchant decisions belong in the ignored naming record, not this file.

## Accomplishment: classification coverage

The session grouped repeating transactions into merchant clusters, asked the
owner for scoped category/note decisions, and encoded those decisions in private
rules. Rows with exceptional circumstances received handwritten overrides.
Every then-collected row had a suggestion or a human entry. This means
**unclassified rows: zero**, not `need-you: zero` or final approval complete.
The CLI at this checkpoint still required row-level human fields, so its
`need-you` count and final refusal were expected.

## Implemented at the checkpoint

- Chase credit-card PDF ingestion: sign normalization, sub-dollar amounts,
  doubled-letter activity headings, summary reconciliation and date checks.
- Venmo CSV ingestion: completed rows and a row-count audit. Weaker than Chase
  deposit-account balance chains; it initially lacked strict invalid-amount
  handling and used path-dependent identity.
- Regex rules with capture substitution in notes; first applicable match wins.
- Configured source exclusions, each with a reason. Unclaimed CSVs and other
  unsupported files can also be explicitly ignored; a CSV extension alone does
  not imply successful ingestion.

## Dates: two valid views, not competing truths

Complete statements are the unit of arithmetic reconciliation. Their printed
periods and row dates—not their filenames—establish evidence dates.
Annotation working files may stay grouped with the source folders.

A tax-year export is a separate derived view: audit complete statements first,
then regroup accepted transactions by their actual dates, retaining IDs and
source links. This does NOT break statement-level reconciliation. January
statements often supply prior-December activity and must be included when
assembling the prior calendar year. Do not edit PDFs or move annotation rows
merely to make filenames agree with transaction years.

## Decisions and policy

- Categories classify; notes carry purpose and uncertainty.
- Transfers, loan principal, reimbursements, refunds and rewards require their
  own interpretation; do not infer taxable income from a positive amount.
- Broker deposits are not automatically deductible expenses.
- Label uncertain cases honestly and leave tax treatment to the professional.
- A human may approve a rule covering recurring transactions rather than typing
  the same decision thousands of times. Preserve rule ID/version provenance.
- Human row overrides outrank automation. BOTH Category and Note must resolve
  for a professional-ready row. Tax Treatment remains optional.
- Rule years refer to transaction dates. Gaps in applicability may be deliberate;
  flag them for review, never automatically extend a rule to fill a year gap.
- Broad rules must not swallow specific exceptions; amount direction and lint
  are required before trusting income classifications.

## Review findings to address

- Add `applies.amount_sign` and correct purchase/income collisions.
- Lint multi-match conflicts, fully shadowed rules and unmatched rows.
- Reject malformed Venmo amounts; retain provider IDs; remove path-dependent IDs
  with a lossless annotation migration and synthetic regressions.
- Report statement coverage separately from extraction accuracy, including known
  unavailable history. Empty discovery is not successful financial coverage.
- Record working-tree state and hashes of actual code, private rules, annotations
  and source evidence. Do not call a dirty final build reproducible.
- Implement field-level resolution from human overrides and accepted rules;
  timeline/LLM evidence is future work with explicit evidence eligibility.

## Future context adapter

Use a normalized evidence interface independent of Discord. Preserve event time,
authorization/purchase date and bank posting date separately. An LLM-generated
explanation does not outrank an approved rule merely because it exists. Require
specific supporting evidence, confidence/match criteria and contradiction flags.
No timeline inference or network ingestion was implemented in this checkpoint.

## Recovery and privacy

The owner keeps external private snapshots. Public branches cannot contain
private sub-branches; a separate private repository or encrypted off-device
backup is needed for remote private storage. Preserve actual rules and context
privately; keep public handovers technical and free of personal financial facts.
