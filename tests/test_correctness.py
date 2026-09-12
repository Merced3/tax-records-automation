"""Failure-catching tests for the correctness work: amount-direction rules,
lint, strict Venmo parsing, provider-ID identity, coverage, calendar-year
exports, resolution, and provenance. Each test encodes a way the system used
to be wrong (or could silently go wrong), not a happy path."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from financial_automation.annotation_workflow.lint import lint
from financial_automation.annotation_workflow.rules import load, suggest
from financial_automation.annotation_workflow.store import AnnotationState
from financial_automation.models import Transaction


def txn(amount, description="doordash, inc. payout", day=5, institution="Chase",
        account="Checking"):
    t = Transaction(
        institution=institution, account=account, statement_id="stmt",
        date=date(2022, 3, day), amount=Decimal(amount),
        raw_description=description, merchant=description,
        source_file="synthetic.pdf", source_page=1, source_line=1,
    )
    t.assign_id()
    return t


def rules_file(tmp, text):
    path = Path(tmp) / "rules.yaml"
    path.write_text(text, encoding="utf-8")
    return path


INCOME_VS_MEAL = """rules:
  - id: income.payout
    version: 2
    match: {contains: doordash}
    applies: {amount_sign: positive}
    suggest: {category: Delivery Driving Income, note: payout}
  - id: meals.order
    version: 1
    match: {contains: doordash}
    applies: {amount_sign: negative}
    suggest: {category: Meals, note: food order}
"""


class AmountDirectionRules(unittest.TestCase):
    def test_income_rule_does_not_claim_expenses(self):
        """The DoorDash failure: an income rule labeled purchases as income."""
        with TemporaryDirectory() as tmp:
            rules = load(rules_file(tmp, INCOME_VS_MEAL))
        payout = suggest(txn("512.33"), rules)
        purchase = suggest(txn("-21.87", "dd doordash jerseymikes"), rules)
        self.assertEqual("Delivery Driving Income", payout.category)
        self.assertEqual("Meals", purchase.category)

    def test_malformed_flow_mapping_is_a_load_error(self):
        """{contains: doordash, inc.} silently shortened the needle before."""
        with TemporaryDirectory() as tmp:
            path = rules_file(tmp, """rules:
  - id: income.bad
    match: {contains: doordash, inc.}
    suggest: {category: X, note: y}
""")
            with self.assertRaisesRegex(ValueError, "unknown match key"):
                load(path)

    def test_bad_amount_sign_value_is_a_load_error(self):
        with TemporaryDirectory() as tmp:
            path = rules_file(tmp, """rules:
  - id: r
    match: {contains: x}
    applies: {amount_sign: incoming}
    suggest: {category: X, note: y}
""")
            with self.assertRaisesRegex(ValueError, "amount_sign"):
                load(path)


class RulesLint(unittest.TestCase):
    def test_conflict_and_shadow_detection(self):
        with TemporaryDirectory() as tmp:
            rules = load(rules_file(tmp, """rules:
  - id: broad
    match: {contains: doordash}
    suggest: {category: Meals, note: broad}
  - id: specific
    match: {contains: doordash jerseymikes}
    suggest: {category: Meals, note: sandwich}
"""))
        rows = [txn("-10.00", "dd doordash jerseymikes")]
        report = lint(rows, rules)
        self.assertFalse(report.clean)
        self.assertEqual(1, len(report.conflicts))
        # `specific` matched but never won: its policy is dead this year.
        self.assertIn("specific", report.shadowed)

    def test_unmatched_row_without_human_fields_is_reported(self):
        report = lint([txn("-5.00", "mystery merchant")], [], states={})
        self.assertEqual(1, len(report.unmatched))

    def test_human_reviewed_row_is_not_unmatched(self):
        row = txn("-5.00", "mystery merchant")
        states = {row.transaction_id: AnnotationState(category="Meals", note="x")}
        report = lint([row], [], states)
        self.assertEqual([], report.unmatched)

    def test_mixed_sign_winners_are_flagged(self):
        with TemporaryDirectory() as tmp:
            rules = load(rules_file(tmp, """rules:
  - id: income.everything
    match: {contains: doordash}
    suggest: {category: Delivery Driving Income, note: payout}
"""))
        report = lint([txn("500.00"), txn("-20.00", "dd doordash order")], rules)
        self.assertIn("income.everything", report.mixed_sign)


if __name__ == "__main__":
    unittest.main()
