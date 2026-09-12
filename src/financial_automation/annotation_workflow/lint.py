"""Rule lint: prove which rules actually decide rows, and where they collide.

A rule matching a row is not evidence the match was correct. This lint makes
three failure classes visible instead of silent:

- conflicts: a row matched by several rules that propose different values;
  first-match-wins picks one, but the collision itself needs human review.
- shadowed rules: a rule that matched at least one row yet never won, so its
  policy has no effect for this year's data.
- unmatched rows: rows with neither an applicable rule nor human fields.

It also reports rules whose winning rows mix positive and negative amounts,
because expense/income collisions look exactly like that before they are
corrected with `applies.amount_sign` (a platform that both pays the owner and
charges the owner is matched by one careless rule).
"""

from collections import defaultdict
from dataclasses import dataclass, field

from .rules import applicable


@dataclass
class LintReport:
    conflicts: list = field(default_factory=list)      # (txn, [rules...])
    shadowed: dict = field(default_factory=dict)       # rule_id -> shadow count
    unmatched: list = field(default_factory=list)      # txns without rule/human
    mixed_sign: dict = field(default_factory=dict)     # rule_id -> (pos, neg)
    winners: dict = field(default_factory=dict)        # rule_id -> win count

    @property
    def clean(self):
        return not (self.conflicts or self.shadowed or self.unmatched
                    or self.mixed_sign)


def lint(transactions, rules, states=None):
    states = states or {}
    report = LintReport()
    win_signs = defaultdict(lambda: [0, 0])  # rule_id -> [positive, negative]
    matched_not_first = defaultdict(int)

    for txn in transactions:
        matches = [r for r in rules if applicable(txn, r) is not None]
        state = states.get(txn.transaction_id)
        human = bool(state and state.human_reviewed)
        if not matches:
            if not human:
                report.unmatched.append(txn)
            continue
        winner = matches[0]
        report.winners[winner["id"]] = report.winners.get(winner["id"], 0) + 1
        signs = win_signs[winner["id"]]
        signs[0 if txn.amount > 0 else 1] += 1
        for rule in matches[1:]:
            matched_not_first[rule["id"]] += 1
        distinct = {(str(r.get("suggest", r).get("category", "")),
                     str(r.get("suggest", r).get("note", ""))) for r in matches}
        if len(matches) > 1 and len(distinct) > 1:
            report.conflicts.append((txn, matches))

    for rule_id, count in matched_not_first.items():
        if rule_id not in report.winners:
            report.shadowed[rule_id] = count
    for rule_id, (positive, negative) in win_signs.items():
        if positive and negative:
            report.mixed_sign[rule_id] = (positive, negative)
    return report
