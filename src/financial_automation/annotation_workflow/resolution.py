"""Field-level resolution of Category and Note, with provenance.

Precedence, per owner decision:

1. Transaction-specific human field overrides (always win).
2. Eligible context/timeline evidence (future; not implemented here).
3. An owner-approved applicable rule.

Fields resolve INDEPENDENTLY, so a handwritten note can coexist with a
rule-supplied category. The source of each value is recorded rather than
relabeling rule output as human-typed text.

A rule suggestion is not a decision until the owner approves that rule at a
specific version. Approval is stored durably in `annotations/rule-approvals.yaml`
so recurring transactions do not require thousands of redundant row approvals.
Bumping a rule's version invalidates its approval: the meaning changed, so the
decision must be re-made.
"""

from dataclasses import dataclass, field
from pathlib import Path
import yaml

HUMAN = "human-override"
RULE = "approved-rule"
UNAPPROVED = "unapproved-suggestion"
MISSING = "missing"
STALE = "stale-approval"


@dataclass
class Approval:
    rule_id: str
    version: str
    years: list = field(default_factory=list)   # empty = all years
    approved_at: str = ""
    approved_by: str = "owner"

    def in_scope(self, rule_id, year):
        """Right rule and right year, ignoring version."""
        return (self.rule_id == rule_id
                and (not self.years or int(year) in [int(y) for y in self.years]))

    def covers(self, rule_id, version, year):
        return self.in_scope(rule_id, year) and str(self.version) == str(version)


def load_approvals(path):
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("approvals", [])
    if not isinstance(entries, list):
        raise ValueError("rule approvals file must contain an 'approvals' list")
    approvals = []
    for entry in entries:
        if "rule_id" not in entry or "version" not in entry:
            raise ValueError(f"approval entry needs rule_id and version: {entry}")
        approvals.append(Approval(
            rule_id=str(entry["rule_id"]), version=str(entry["version"]),
            years=entry.get("years") or [], approved_at=str(entry.get("approved_at", "")),
            approved_by=str(entry.get("approved_by", "owner")),
        ))
    return approvals


@dataclass
class Resolved:
    category: str = ""
    category_source: str = MISSING
    note: str = ""
    note_source: str = MISSING
    tax_treatment: str = ""
    tax_treatment_source: str = MISSING
    rule_id: str = ""
    rule_version: str = ""

    @property
    def deliverable(self):
        """Every deliverable row requires BOTH a category and a note.
        Tax Treatment is optional and primarily the professional's call."""
        return bool(self.category.strip()) and bool(self.note.strip())

    @property
    def blockers(self):
        reasons = []
        if not self.category.strip():
            reasons.append(f"category {self.category_source}")
        if not self.note.strip():
            reasons.append(f"note {self.note_source}")
        return reasons


def resolve(transaction, state, approvals):
    """Resolve one row's fields from its human state and rule suggestion.

    `state` carries both the human-typed fields and the recomputed suggestion
    (with rule id/version), so no separate rule evaluation happens here.
    """
    result = Resolved()
    if state is None:
        return result

    result.rule_id = (state.rule_id or "").strip()
    result.rule_version = (state.rule_version or "").strip()
    year = transaction.date.year

    approved = any(a.covers(result.rule_id, result.rule_version, year)
                   for a in approvals) if result.rule_id else False
    # Stale means specifically: the owner approved this rule for this year, but
    # at a different version, so the meaning changed and the decision must be
    # re-made. A year the owner never approved is simply unapproved.
    stale = (not approved and result.rule_id
             and any(a.in_scope(result.rule_id, year) for a in approvals))
    rule_state = RULE if approved else (STALE if stale else UNAPPROVED)

    for field_name, human_value, suggested_value in (
        ("category", state.category, state.suggested_category),
        ("note", state.note, state.suggested_note),
    ):
        human_value = (human_value or "").strip()
        suggested_value = (suggested_value or "").strip()
        if human_value:
            setattr(result, field_name, human_value)
            setattr(result, f"{field_name}_source", HUMAN)
        elif suggested_value and approved:
            setattr(result, field_name, suggested_value)
            setattr(result, f"{field_name}_source", RULE)
        elif suggested_value:
            # Present but not a decision: never exported as a value.
            setattr(result, f"{field_name}_source", rule_state)
        else:
            setattr(result, f"{field_name}_source", MISSING)

    treatment = (state.tax_treatment or "").strip()
    if treatment:
        result.tax_treatment = treatment
        result.tax_treatment_source = HUMAN
    return result


def resolve_all(transactions, states, approvals):
    return {t.transaction_id: resolve(t, states.get(t.transaction_id), approvals)
            for t in transactions}
