"""Rules engine: suggest Category/Note for transactions automatically.

Design intent (decoupled, see decisions.md):

- Rules live in tools/rules.yaml — plain data the human owns and edits,
  NOT code. Adding "Circle K -> Fuel" is a one-line edit, no programming.
- A rule MATCHES on the merchant/description text and SUGGESTS a category
  and/or note. Suggestions never overwrite a cell the human already filled.
- The engine is a pure function: (transaction, rules) -> suggestion. It has
  no idea where transactions come from or where suggestions go. That seam is
  what lets a future front-end (a Discord bot, a TUI, a phone) reuse the
  exact same matching logic — the "automation center" idea.

Rule shape (rules.yaml):

    - match: "chick-fil-a"        # substring, case-insensitive
      category: Meals
      note: ""                    # optional
    - match: "circle k"
      category: Fuel

First matching rule wins, so put specific rules before general ones.
"""

import os

import yaml

from annotations.store import Annotation


def load_rules(path):
    """Read rules.yaml. Missing file = no rules (everything stays manual)."""
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data if isinstance(data, list) else []


def suggest(transaction, rules):
    """Return an Annotation suggested for this transaction, or empty.

    Matches against both the cleaned merchant name and the raw bank
    description (rules can target either). Pure: no I/O, no mutation.
    """
    haystack = f"{transaction.merchant}\n{transaction.description}".lower()
    for rule in rules:
        needle = str(rule.get("match", "")).lower()
        if needle and needle in haystack:
            return Annotation(
                category=str(rule.get("category", "")),
                note=str(rule.get("note", "")),
            )
    return Annotation()
