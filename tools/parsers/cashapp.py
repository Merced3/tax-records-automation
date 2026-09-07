"""Parser for Cash App monthly account statements (PDF).

Layout differs completely from Chase — hence the plugin system.
Transaction lines look like:

    Mar 4 From Zion Montelongo Cash App payment $0.00 + $200.00
    Mar 2 To Visa Debit 9663 x9663 Instant transfer $9.47 $541.00

Columns: date (no year — stamped from the folder), description, details,
fee, amount. Only the amount matters to us; a leading "+" marks money in,
and money out has no sign (we negate it ourselves).
"""

import re

import pdfplumber

from parsers.base import StatementParser
from pipeline.models import Transaction

_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"

# Mar 2 <description> ... $<fee> [+] $<amount>
TXN_RE = re.compile(
    rf"^(({_MONTHS})\s+\d{{1,2}})\s+(.+?)\s+\$([\d,]+\.\d{{2}})\s+(\+?)\s*\$([\d,]+\.\d{{2}})\s*$"
)

# The "Details" column words that end the description text.
_DETAILS = ("Cash App payment", "Instant transfer", "Standard transfer", "Card payment")


class CashAppParser(StatementParser):
    name = "cashapp"

    def can_parse(self, first_page_text, path):
        return "Account Statement" in first_page_text and "Cash App" in first_page_text

    def parse(self, path, source_account, year):
        transactions = []
        in_txns = False
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("Transactions"):
                        in_txns = True
                        continue
                    if in_txns and line.startswith("All transactions shown"):
                        in_txns = False
                        continue
                    if not in_txns or line.startswith(("Date Description", "Date ")):
                        continue

                    m = TXN_RE.match(line)
                    if m:
                        date_s, _mon, desc, _fee, plus, amount_s = m.groups()
                        transactions.append(self._make_txn(
                            date_s, desc, plus, amount_s, source_account, path, year
                        ))
        return transactions

    def _make_txn(self, date_s, desc, plus, amount_s, account, path, year):
        amount = float(amount_s.replace(",", ""))
        if not plus:
            amount = -amount
        date = self._to_date(date_s, year)
        merchant = desc
        for d in _DETAILS:
            if merchant.endswith(d):
                merchant = merchant[: -len(d)].strip()
                break
        return Transaction(
            amount=amount,
            date=date,
            merchant=merchant or desc,
            description=desc,
            source_account=account,
            source_file=str(path),
        )

    @staticmethod
    def _to_date(date_s, year):
        mon, day = date_s.split()
        month_num = {
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
        }[mon]
        return f"{month_num:02d}/{int(day):02d}/{year}"
