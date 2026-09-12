# Rule lifecycle and yearly context

## Rules classify; humans decide

A merchant match can suggest `Fuel`, `Meals`, or `Software`. It cannot prove a
business purpose or deduction. Tax Treatment and Note remain human-owned.

## Private schema

```yaml
rules:
  - id: merchant.example
    version: 2
    match:
      contains: Example Merchant
    applies:
      years: [2022, 2023]
      institutions: [Chase]
      accounts: [Everyday Spend Bank Account]
      amount_sign: negative      # negative = money out, positive = money in
    suggest:
      category: Fuel
      note: Needs trip-purpose review
```

- `id` never changes; it identifies the policy.
- `version` increases when meaning/output changes.
- `applies` makes context explicit. Omitted dimensions mean all.
- First matching rule wins; specific rules belong before general ones.
- Suggestions are recomputed on every annotation refresh.
- Human fields are never overwritten.
- Unknown `match`/`applies` keys and invalid `amount_sign` values are load
  errors, not ignored text.

## Direction matters

A company name appears in both its payouts and its purchases. Without
`amount_sign`, one rule claims both.

This actually happened in the private rules. A needle written as
`match: {contains: example co, inc.}` is YAML flow-mapping syntax, so the
unquoted comma produced **two keys** — `contains: example co` plus a stray
`inc.: null` — silently shortening the needle. A gig platform's payout rule
then also matched purchases made through that platform, labelling expenses as
income. Quote needles containing commas, and scope income rules to `positive`.

`python run.py rules-lint <year>` reports rules whose winning rows mix signs,
along with conflicts, dead (fully shadowed) rules, and rows nothing decides.
Mixed signs are not automatically wrong — refunds and reimbursements are real —
so the lint reports them for human review instead of guessing.

## Year context

Tax-professional summaries remain private plain `.txt` files because that is
what the professional's software accepts. Free-form prose is not executable
policy. If automation needs yearly facts later, store them separately in a
private structured context file and require explicit values/dates.

Example future context:

```yaml
activities:
  delivery_driving:
    active_from: 2022-01-01
    active_to: 2025-12-31
```

A Discord/TUI/web interface should display a suggestion, its rule ID/version,
and transaction evidence, then store approval or override in the human fields.
It must not modify rules merely because one exceptional transaction differs.
