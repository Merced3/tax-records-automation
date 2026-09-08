"""Small regression suite: every test represents a failure we actually found."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from financial_automation.annotation_workflow.rules import suggest
from financial_automation.annotation_workflow.store import generate, load_states
from financial_automation.auditing.reconcile import AuditReport, _audit_cashapp, _audit_chase
from financial_automation.ingestion.chase import ChaseParser
from financial_automation.ingestion.cashapp import CashAppParser
from financial_automation.models import ParsedStatement, Transaction
from financial_automation.pipeline import PipelineReport, _dedupe_cross_statement, discover


CHASE_HEADER = "January 01, 2024 through January 31, 2024\nJPMorgan Chase Bank, N.A."


def chase_page(marker="*start*transaction detail", rows=""):
    return f"{CHASE_HEADER}\n{marker}\nTRANSACTION DETAIL\nDATE DESCRIPTION AMOUNT BALANCE\nBeginning Balance $0.00\n{rows}\nEnding Balance $0.00\n*end*transaction detail"


class ChaseParserRegressions(unittest.TestCase):
    def parse(self, text, year=2024):
        return ChaseParser().parse_pages([text], "synthetic.pdf", "Checking", year)

    def test_spaced_and_unspaced_markers(self):
        row = "01/02 Card Purchase Example -5.00 -5.00"
        self.assertEqual(1, len(self.parse(chase_page(rows=row)).transactions))
        self.assertEqual(1, len(self.parse(chase_page("*start*transactiondetail", row)).transactions))

    def test_fused_end_date_leading_zero(self):
        text = chase_page(rows="").replace(
            "*end*transaction detail",
            "*end*transac0tion detail7/15 Example Purchase -5.00 -5.00")
        # Period must cover July.
        text = text.replace("January 01, 2024 through January 31, 2024",
                            "July 01, 2024 through July 31, 2024")
        txn = self.parse(text).transactions[0]
        self.assertEqual(date(2024, 7, 15), txn.date)

    def test_fused_end_date_leading_one(self):
        text = chase_page(rows="").replace(
            "*end*transaction detail",
            "*end*transac1tion detail0/31 Example Purchase -5.00 -5.00")
        text = text.replace("January 01, 2024 through January 31, 2024",
                            "October 01, 2024 through October 31, 2024")
        self.assertEqual(date(2024, 10, 31), self.parse(text).transactions[0].date)

    def test_december_to_january_uses_both_years(self):
        text = chase_page(rows=(
            "12/20 December Purchase -5.00 -5.00\n"
            "01/03 January Purchase -5.00 -10.00"
        )).replace("January 01, 2024 through January 31, 2024",
                   "December 09, 2023 through January 09, 2024")
        rows = self.parse(text).transactions
        self.assertEqual([date(2023, 12, 20), date(2024, 1, 3)], [r.date for r in rows])

    def test_identical_rows_have_unique_ids(self):
        text = chase_page(rows=(
            "01/02 Card Purchase Same -5.00 -5.00\n"
            "01/02 Card Purchase Same -5.00 -10.00"
        ))
        rows = self.parse(text).transactions
        self.assertEqual(rows[0].content_fingerprint, rows[1].content_fingerprint)
        self.assertNotEqual(rows[0].transaction_id, rows[1].transaction_id)

    def test_wrapped_description_is_joined_before_identity(self):
        text = chase_page(rows=(
            "01/02 Card Purchase Long Merchant -5.00 -5.00\n"
            "Card 1234"
        ))
        txn = self.parse(text).transactions[0]
        self.assertIn("Card 1234", txn.raw_description)
        # Reparse is stable.
        self.assertEqual(txn.transaction_id, self.parse(text).transactions[0].transaction_id)

    def test_empty_chase_statement_is_explicitly_empty(self):
        statement = self.parse(chase_page(rows=""))
        self.assertEqual([], statement.transactions)
        self.assertEqual(date(2024, 1, 1), statement.period_start)


class CashAppRegressions(unittest.TestCase):
    def test_bank_funded_payment_reconciles_per_month(self):
        pages = [
            "January 2025\nAccount Statement\nCash App Example\n"
            "Balance on Jan 1 Change this month Balance on Jan 31\n"
            "$0.00 $0.00 $0.00\nMoney In + $10.00\nMoney Out - $10.00",
            "January 2025\nAccount Statement\nTransactions\n"
            "Date Description Details Fee Amount\n"
            "Jan 2 From Friend Cash App payment $0.00 + $10.00\n"
            "Jan 2 To Bank Standard transfer $0.00 $10.00\n"
            "Jan 3 To Friend from Chase Bank x1234 Cash App payment $0.00 $5.00",
        ]
        statement = CashAppParser().parse_pages(pages, "jan.pdf", "CashApp", 2025)
        report = AuditReport(2025)
        with patch("financial_automation.auditing.reconcile._pages", return_value=[pages[0]]):
            _audit_cashapp(report, [statement])
        self.assertTrue(report.passed, [c.detail for c in report.checks])

    def test_empty_statement_has_zero_transactions(self):
        pages = ["February 2025\nAccount Statement\nCash App Example\n"
                 "Balance on Feb 1 Change this month Balance on Feb 28\n$0.00 $0.00 $0.00"]
        statement = CashAppParser().parse_pages(pages, "feb.pdf", "CashApp", 2025)
        self.assertEqual([], statement.transactions)


class IdentityAndSafetyRegressions(unittest.TestCase):
    def txn(self, statement="s", balance="5.00", occurrence=1):
        t = Transaction("Chase", "Checking", statement, date(2024, 1, 2),
                        Decimal("5.00"), "Example", "Example", "x.pdf", 1, 1,
                        balance=Decimal(balance), occurrence=occurrence)
        t.assign_id(); return t

    def test_cross_statement_dedupe_preserves_same_statement_repeats(self):
        a1, a2 = self.txn("a", "5.00", 1), self.txn("a", "10.00", 1)
        # Same content repeats in overlapping statement B.
        b1, b2 = self.txn("b", "5.00", 1), self.txn("b", "10.00", 1)
        sa = ParsedStatement("a", "chase", "Chase", "Checking", "a",
                             date(2024,1,1), date(2024,1,31), [a1,a2], "x")
        sb = ParsedStatement("b", "chase", "Chase", "Checking", "b",
                             date(2024,1,1), date(2024,1,31), [b1,b2], "y")
        report = PipelineReport(statements=[sa,sb])
        _dedupe_cross_statement(report)
        self.assertEqual(2, len(report.transactions))
        self.assertEqual(2, report.duplicates_removed)

    def test_year_specific_rule(self):
        txn = self.txn()
        rules = [{"id":"r", "version":1, "match":{"contains":"Example"},
                  "applies":{"years":[2024]}, "suggest":{"category":"Fuel"}}]
        self.assertEqual("Fuel", suggest(txn, rules).category)
        txn.date = date(2025,1,2)
        self.assertFalse(suggest(txn, rules).present)

    def test_annotation_write_backs_up_and_preserves_human_text(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); path = root / "annotations" / "2024.csv"
            txn = self.txn()
            # Create new schema once, then emulate a human edit.
            generate([txn], path, [], root)
            with path.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            rows[0]["Note"] = "human explanation"
            with path.open("w", newline="", encoding="utf-8") as f:
                writer=csv.DictWriter(f,fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
            rules = [{"id":"r", "version":2, "match":{"contains":"Example"},
                      "suggest":{"category":"Suggested"}}]
            generate([txn], path, rules, root)
            state = load_states(path)[txn.transaction_id]
            self.assertEqual("human explanation", state.note)
            self.assertEqual("Suggested", state.suggested_category)
            self.assertTrue(any((root / "backups").rglob("2024.csv")))
            self.assertTrue((root / "backups" / "journal.jsonl").exists())

            # Delete the whole annotated row. The next run restores both the
            # transaction and its human text from the private baseline.
            with path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(rows[0].keys())
            result = generate([txn], path, rules, root)
            self.assertEqual(1, result["deleted_rows_restored"])
            self.assertEqual("human explanation",
                             load_states(path)[txn.transaction_id].note)

    def test_discovery_sees_non_pdf_sources(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp) / "2024" / "Bank Statements" / "Venmo"
            folder.mkdir(parents=True)
            (folder / "Jan.csv").write_text("data", encoding="utf-8")
            (folder / "notes.txt").write_text("note", encoding="utf-8")
            self.assertEqual(["Jan.csv", "notes.txt"],
                             [p.name for p in discover(temp, 2024)])


if __name__ == "__main__":
    unittest.main()
