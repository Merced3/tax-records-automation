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
    return rules


def suggest(transaction, rules):
    haystack = f"{transaction.merchant}\n{transaction.raw_description}".lower()
    for rule in rules:
        applies = rule.get("applies", {}) or {}
        years = applies.get("years")
        institutions = applies.get("institutions")
        accounts = applies.get("accounts")
        if years and transaction.date.year not in [int(y) for y in years]:
            continue
        if institutions and transaction.institution not in institutions:
            continue
        if accounts and transaction.account not in accounts:
            continue
        match = rule.get("match", {})
        groups = ()
        if isinstance(match, dict) and match.get("regex"):
            found = re.search(str(match["regex"]), haystack)
            if not found:
                continue
            groups = found.groups()
        else:
            needle = match.get("contains") if isinstance(match, dict) else match
            if not needle or str(needle).lower() not in haystack:
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
