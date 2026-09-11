"""Chase credit card statement parser (Freedom Flex format).

Statement pages mix marketing text with a clean table. The doubled-letter
headers ("AACCCCOOUUNNTT AACCTTIIVVIITTYY") are a pdfplumber artifact of
bold text; the printed summary labels themselves ("Previous Balance",
"Opening/Closing Date") extract cleanly and anchor everything.

Sign convention matches the bank model: purchases/fees/interest are negative
(expenses), payments/credits are positive.
"""

from collections import Counter
from datetime import date
from decimal import Decimal
import re

import pdfplumber

from .base import StatementParser
from .chase import clean_merchant
from ..models import ParsedStatement, Transaction, digest, money
from ..safety import sha256_file

_PERIOD = re.compile(r"Opening/Closing Date (\d{2}/\d{2}/\d{2}) - (\d{2}/\d{2}/\d{2})")
_ROW = re.compile(r"^(\d{2}/\d{2})\s+(.+?)\s+(-?[\d,]*\.\d{2})$")
_ACTIVITY = "AACCCCOOUUNNTT AACCTTIIVVIITTYY"
_END = ("Totals Year-to-Date", "IINNTTEERREESSTT CCHHAARRGESS")
_CREDIT = "PAYMENTS AND OTHER CREDITS"
_CHARGES = ("PURCHASE", "FEES CHARGED", "INTEREST CHARGED")


class ChaseCreditParser(StatementParser):
    name = "chase-credit"

    def can_parse(self, first_page_text, path):
        return "Opening/Closing Date" in first_page_text

    def parse(self, path, account, fallback_year):
        with pdfplumber.open(path) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return self.parse_pages(pages, str(path), account, fallback_year,
                                sha256_file(path))

    def parse_pages(self, pages, path, account, fallback_year, source_hash="synthetic"):
        period = self._period("\n".join(pages[:2]))
        statement_id = digest("chase-credit", account, period[0], period[1])
        raw_rows = []
        in_activity = False
        credit = False

        for page_number, text in enumerate(pages, 1):
            for line_number, raw in enumerate(text.splitlines(), 1):
                line = raw.strip()
                if _ACTIVITY in line:
                    in_activity = True
                    continue
                if in_activity and any(end in line for end in _END):
                    in_activity = False
                    continue
                if in_activity and _CREDIT in line:
                    credit = True
                    continue
                if in_activity and any(charge in line for charge in _CHARGES):
                    credit = False
                    continue
                if not in_activity or not line:
                    continue
                match = _ROW.match(line)
                if match:
                    mmdd, description, amount = match.groups()
                    sign = Decimal("1") if credit else Decimal("-1")
                    raw_rows.append({"mmdd": mmdd, "description": description,
                                     "amount": sign * abs(money(amount)),
                                     "page": page_number, "line": line_number})
                elif raw_rows and not line.startswith("Page"):
                    raw_rows[-1]["description"] += " " + line

        transactions = []
        occurrence_counts = Counter()
        for row in raw_rows:
            txn_date = self._date(row["mmdd"], period)
            base = (txn_date.isoformat(), row["amount"], row["description"])
            occurrence_counts[base] += 1
            txn = Transaction(
                institution="Chase", account=account, statement_id=statement_id,
                date=txn_date, amount=row["amount"],
                raw_description=row["description"],
                merchant=clean_merchant(row["description"]),
                source_file=path, source_page=row["page"], source_line=row["line"],
                occurrence=occurrence_counts[base],
            )
            txn.assign_id()
            transactions.append(txn)

        return ParsedStatement(
            path=path, parser_name=self.name, institution="Chase", account=account,
            statement_id=statement_id, period_start=period[0], period_end=period[1],
            transactions=transactions, source_sha256=source_hash,
        )

    @staticmethod
    def _period(text):
        match = _PERIOD.search(text)
        if not match:
            raise ValueError("Chase credit statement period not found")
        start, end = match.groups()
        return (date(*_parts(start)), date(*_parts(end)))

    @staticmethod
    def _date(mmdd, period):
        month, day = map(int, mmdd.split("/"))
        start, end = period
        year = start.year if start.year != end.year and month == 12 else end.year
        return date(year, month, day)


def _parts(mmddyy):
    month, day, year = mmddyy.split("/")
    return int("20" + year), int(month), int(day)
