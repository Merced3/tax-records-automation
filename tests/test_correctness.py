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


VENMO_CSV = """Account Statement - (@user) ,,,,,,,,,,,,,,,,,,,,,
Account Activity,,,,,,,,,,,,,,,,,,,,,
,ID,Datetime,Type,Status,Note,From,To,Amount (total),Amount (tip),Amount (tax),Amount (fee),Tax Rate,Tax Exempt,Funding Source,Destination,Beginning Balance,Ending Balance,Statement Period Venmo Fees,Terminal Location,Year to Date Venmo Fees,Disclaimer
,,,,,,,,,,,,,,,,$0.00,,,,,
,111,2024-02-03T10:00:00,Payment,Complete,Food,Alex,User,+ $50.00,,,,,,,Venmo balance,,,,Venmo,,
,222,2024-02-04T10:00:00,Payment,Complete,,User,Store,- $50.00,,,,,,Visa *1234,,,,,Venmo,,
,333,2024-02-05T10:00:00,Payment,Cancelled,,,,- $99.00,,,,,,Venmo balance,,,,,Venmo,,
,,,,,,,,,,,,,,,,,$50.00,$0.00,,$0.00,disclaimer
"""


def parse_venmo(text=VENMO_CSV, path="synthetic/Feb.csv"):
    from financial_automation.ingestion.venmo import VenmoParser
    return VenmoParser().parse_text(text, path, "Venmo", 2024)


class StrictVenmoParsing(unittest.TestCase):
    def test_malformed_amount_raises_instead_of_zero(self):
        """Silently returning 0.00 let a bad row pass a row-count audit."""
        broken = VENMO_CSV.replace("+ $50.00", "+ $5O.OO")
        with self.assertRaisesRegex(ValueError, "unparsable Venmo amount"):
            parse_venmo(broken)

    def test_non_moving_status_is_skipped_and_counted(self):
        statement = parse_venmo()
        self.assertEqual(2, len(statement.transactions))
        self.assertEqual({"Cancelled": 1}, statement.metadata["skipped_statuses"])

    def test_identity_comes_from_provider_id_not_path(self):
        """Moving or renaming an export must not change transaction identity."""
        a = parse_venmo(path="records/2024/Bank Statements/Venmo/Feb.csv")
        b = parse_venmo(path="somewhere/else/Feb-copy.csv")
        self.assertEqual([t.transaction_id for t in a.transactions],
                         [t.transaction_id for t in b.transactions])
        self.assertEqual(a.statement_id, b.statement_id)

    def test_duplicate_provider_id_is_an_error(self):
        dup = VENMO_CSV.replace(",222,", ",111,")
        with self.assertRaisesRegex(ValueError, "duplicate Venmo ID"):
            parse_venmo(dup)

    def test_balance_chain_audit_catches_wrong_direction(self):
        from financial_automation.auditing.reconcile import AuditReport, _audit_venmo
        from pathlib import Path as P
        with TemporaryDirectory() as tmp:
            good = P(tmp) / "Feb.csv"
            good.write_text(VENMO_CSV, encoding="utf-8")
            statement = parse_venmo(VENMO_CSV, str(good))
            report = AuditReport(2024)
            _audit_venmo(report, [statement])
            self.assertTrue(report.passed, [c.detail for c in report.checks])

            # Flip the card-funded payment to balance-funded: the printed
            # ending balance can no longer be reached.
            bad = P(tmp) / "Bad.csv"
            bad.write_text(VENMO_CSV.replace(",,Visa *1234,,", ",,,Venmo balance,"),
                           encoding="utf-8")
            broken = parse_venmo(bad.read_text(encoding="utf-8"), str(bad))
            report = AuditReport(2024)
            _audit_venmo(report, [broken])
            self.assertFalse(report.passed)
            self.assertIn("Venmo balance chain",
                          [c.name for c in report.checks if not c.passed])


class IdentityMigration(unittest.TestCase):
    def test_human_text_follows_a_changed_transaction_id(self):
        """Switching Venmo to provider IDs must not orphan human notes."""
        from financial_automation.annotation_workflow.store import generate, load_states
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "annotations").mkdir()
            path = root / "annotations" / "2024.csv"
            row = parse_venmo().transactions[0]
            generate([row], path, [], root)

            # Simulate the human typing a decision, then an identity change.
            import csv as _csv
            with path.open(newline="", encoding="utf-8") as f:
                rows = list(_csv.DictReader(f))
            rows[0]["Category"] = "Reimbursement"
            rows[0]["Note"] = "friend paid me back for dinner"
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = _csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            moved = parse_venmo().transactions[0]
            moved.provider_id = ""           # force the old identity scheme
            moved.assign_id()
            self.assertNotEqual(row.transaction_id, moved.transaction_id)
            result = generate([moved], path, [], root)
            state = load_states(path)[moved.transaction_id]
            self.assertEqual("friend paid me back for dinner", state.note)
            self.assertEqual("Reimbursement", state.category)
            self.assertEqual(1, result["legacy_migrated"])

    def test_unmatched_human_row_still_aborts(self):
        """The safety stop must survive the new content-based fallback."""
        from financial_automation.annotation_workflow.store import generate
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "annotations").mkdir()
            path = root / "annotations" / "2024.csv"
            row = parse_venmo().transactions[0]
            generate([row], path, [], root)
            import csv as _csv
            with path.open(newline="", encoding="utf-8") as f:
                rows = list(_csv.DictReader(f))
            rows[0]["Note"] = "irreplaceable human text"
            rows[0]["Amount"] = "-1234.56"      # no longer any such transaction
            rows[0]["Transaction ID"] = "stale"
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = _csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            before = path.read_text(encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "SAFETY STOP"):
                generate([row], path, [], root)
            self.assertEqual(before, path.read_text(encoding="utf-8"))


def statement(account="Checking", start=(1, 1), end=(1, 31), year=2024,
              period_source="printed", institution="Chase", rows=()):
    from financial_automation.models import ParsedStatement
    return ParsedStatement(
        path=f"synthetic/{account}-{start}-{end}.pdf", parser_name="chase",
        institution=institution, account=account, statement_id=f"{account}{start}{end}",
        period_start=date(year, *start), period_end=date(year, *end),
        transactions=list(rows), source_sha256="x", period_source=period_source)


class Coverage(unittest.TestCase):
    def report(self, statements, known=None, adjacent=()):
        from financial_automation.auditing.coverage import coverage
        from financial_automation.models import PipelineReport
        pipeline = PipelineReport(statements=list(statements))
        return coverage(2024, pipeline, known, adjacent)

    def test_missing_middle_statement_is_found(self):
        """Every statement can reconcile while a whole cycle is absent.
        This is the real 2024 Everyday Spend gap, reduced to synthetic data."""
        report = self.report([
            statement(start=(1, 1), end=(5, 8)),
            statement(start=(6, 11), end=(12, 31)),
        ])
        account = report.accounts[0]
        self.assertEqual([(date(2024, 5, 9), date(2024, 6, 10))], account.gaps)
        self.assertEqual(33, report.undeclared_gap_days)
        self.assertFalse(report.complete)

    def test_no_discovered_statements_is_not_success(self):
        """Empty discovery must never look like complete coverage."""
        report = self.report([])
        self.assertFalse(report.complete)

    def test_december_is_covered_by_next_january_statement(self):
        """Cycles cross calendar years; this must not be a false gap."""
        report = self.report(
            [statement(start=(1, 1), end=(12, 8))],
            adjacent=[statement(start=(12, 9), end=(12, 31))])
        self.assertEqual([], report.accounts[0].gaps)
        self.assertTrue(report.complete)
        # Adjacent statements provide evidence but are not counted as this
        # year's statements.
        self.assertEqual(1, report.accounts[0].statements)

    def test_known_missing_history_is_disclosed_not_hidden(self):
        known = [{"year": 2024, "institution": "Capital One", "account": "unknown",
                  "period": "unknown", "reason": "owner cannot access account"}]
        report = self.report([statement(start=(1, 1), end=(12, 31))], known)
        self.assertEqual(1, len(report.known_gaps))
        # Declared missing history means the year is still not complete.
        self.assertFalse(report.complete)

    def test_derived_period_source_is_unmeasurable_not_a_gap(self):
        """Venmo exports print no period: inventing gaps from row dates would
        misreport 'no rows that week' as 'records missing that week'."""
        rows = parse_venmo().transactions
        venmo = statement(account="Venmo", institution="Venmo", start=(2, 3),
                          end=(2, 4), period_source="derived", rows=rows)
        report = self.report([venmo])
        entry = report.accounts[0]
        self.assertTrue(entry.period_unmeasurable)
        self.assertEqual([], entry.gaps)
        self.assertEqual(0, report.undeclared_gap_days)
        self.assertFalse(report.complete)   # unmeasurable is not proven-complete
