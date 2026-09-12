"""Year-aware suggestion rules. Rules classify; humans decide tax treatment."""

from dataclasses import dataclass
from pathlib import Path
import re
import yaml


@dataclass
class Suggestion:
    category: str = ""
    note: str = ""
    rule_id: str = ""
    rule_version: str = ""

    @property
    def present(self):
        return bool(self.category or self.note)


_MATCH_KEYS = {"contains", "regex"}
_APPLIES_KEYS = {"years", "institutions", "accounts", "amount_sign"}
_SIGNS = {"positive", "negative"}


def _validate(rule):
    """Reject silently-broken rules instead of matching the wrong rows.

    A YAML flow mapping like {contains: example co, inc.} parses as TWO keys
    and quietly shortens the needle; that exact failure made a payout rule
    match purchases too, labelling expenses as income. Unknown keys are
    therefore load errors.
    """
    match = rule.get("match", {})
    if isinstance(match, dict):
        unknown = set(match) - _MATCH_KEYS
        if unknown:
            raise ValueError(
                f"rule {rule['id']}: unknown match key(s) {sorted(unknown)} "
                "(quote needles containing commas, e.g. contains: 'example co, inc.')")
        if "contains" in match and "regex" in match:
            raise ValueError(f"rule {rule['id']}: use contains OR regex, not both")
        if not (match.get("contains") or match.get("regex")):
            raise ValueError(f"rule {rule['id']}: empty match")
    elif not match:
        raise ValueError(f"rule {rule['id']}: missing match")
    applies = rule.get("applies") or {}
    unknown = set(applies) - _APPLIES_KEYS
    if unknown:
        raise ValueError(f"rule {rule['id']}: unknown applies key(s) {sorted(unknown)}")
    sign = applies.get("amount_sign")
    if sign is not None and sign not in _SIGNS:
        raise ValueError(f"rule {rule['id']}: amount_sign must be one of {sorted(_SIGNS)}")


def load(path):
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = data.get("rules", data if isinstance(data, list) else [])
    if not isinstance(rules, list):
        raise ValueError("rules file must contain a 'rules' list")
    seen = set()
    for index, rule in enumerate(rules, 1):
        rule.setdefault("id", f"legacy.rule.{index}")
        rule.setdefault("version", 1)
        if rule["id"] in seen:
            raise ValueError(f"duplicate rule id: {rule['id']}")
        seen.add(rule["id"])
        _validate(rule)
    return rules


def applicable(transaction, rule):
    """True when the rule's scope AND match apply to this transaction."""
    applies = rule.get("applies", {}) or {}
    years = applies.get("years")
    institutions = applies.get("institutions")
    accounts = applies.get("accounts")
    sign = applies.get("amount_sign")
    if years and transaction.date.year not in [int(y) for y in years]:
        return None
    if institutions and transaction.institution not in institutions:
        return None
    if accounts and transaction.account not in accounts:
        return None
    if sign == "positive" and transaction.amount <= 0:
        return None
    if sign == "negative" and transaction.amount >= 0:
        return None
    haystack = f"{transaction.merchant}\n{transaction.raw_description}".lower()
    match = rule.get("match", {})
    if isinstance(match, dict) and match.get("regex"):
        found = re.search(str(match["regex"]), haystack)
        return found.groups() if found else None
    needle = match.get("contains") if isinstance(match, dict) else match
    if needle and str(needle).lower() in haystack:
        return ()
    return None


def suggest(transaction, rules):
    for rule in rules:
        groups = applicable(transaction, rule)
        if groups is None:
            continue
        proposed = rule.get("suggest", {})
        # Backward-compatible old shape while private rules migrate.
        category = proposed.get("category", rule.get("category", ""))
        note = proposed.get("note", rule.get("note", ""))
        return Suggestion(str(category or ""), _fill(str(note or ""), groups),
                          str(rule["id"]), str(rule["version"]))
    return Suggestion()


def _fill(note, groups):
    """Substitute {1}..{9} with regex capture groups; unknown tokens stay."""
    for index, value in enumerate(groups, 1):
        note = note.replace("{" + str(index) + "}", value or "")
    return note
