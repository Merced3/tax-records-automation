"""Venmo monthly CSV statement parser.

Venmo personal-account exports have no printed statement totals, so the audit
can only check date coverage and row sanity — unlike the PDF statements, there
is nothing independent to reconcile against. The PDFs remain authoritative
where they exist; Venmo activity is overwhelmingly person-to-person.

Amount convention matches the bank model: "- $10.00" is money out (negative),
"+ $20.00" is money in (positive).
"""

from collections import Counter
from datetime import datetime
from decimal import Decimal
import csv
import io
import re

from .base import StatementParser
from ..models import ParsedStatement, Transaction, digest, money
from ..safety import sha256_file

_HEADER = ",ID,Datetime,Type,Status,Note,From,To,Amount (total)"
_AMOUNT = re.compile(r"^([+-]?)\s*\$?([\d,]+\.\d{2})$")


class VenmoParser(StatementParser):
    name = "venmo"

    def can_parse(self, first_page_text, path):
        return "Statement Period Venmo Fees" in first_page_text or _HEADER in first_page_text

    def parse(self, path, account, fallback_year):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        return self.parse_text(text, str(path), account, fallback_year,
                               sha256_file(path))

    def parse_text(self, text, path, account, fallback_year, source_hash="synthetic"):
        rows = list(csv.reader(io.StringIO(text)))
        header_at = next((i for i, r in enumerate(rows)
                          if r and r[1:3] == ["ID", "Datetime"]), None)
        if header_at is None:
            raise ValueError("Venmo transaction header not found")

        transactions = []
        occurrence = Counter()
        dates = []
        for index, row in enumerate(rows[header_at + 1:], header_at + 2):
            if len(row) < 8 or not (row[1].strip().isdigit() and row[2].strip()):
                continue  # balance filler row and disclaimer footer
            row_id, when, kind, status = row[1], row[2], row[3], row[4]
            if status.strip() != "Complete":
                continue
            amount = _amount(row[8])
            txn_date = datetime.fromisoformat(when.strip()).date()
            dates.append(txn_date)
            note = row[5].strip()
            who_from = row[6].strip()
            who_to = row[7].strip()
            description = _description(kind, who_from, who_to, note)
            base = (txn_date.isoformat(), amount, description)
            occurrence[base] += 1
            txn = Transaction(
                institution="Venmo", account="Venmo",
                statement_id="",  # filled after period is known
                date=txn_date, amount=amount, raw_description=description,
                merchant=description, source_file=path,
                source_page=1, source_line=index,
                occurrence=occurrence[base],
            )
            transactions.append(txn)

        if not dates:
            start = end = datetime(fallback_year, 1, 1).date()
        else:
            start, end = min(dates), max(dates)
        statement_id = digest("venmo", path, start, end)
        for txn in transactions:
            txn.statement_id = statement_id
            txn.assign_id()

        return ParsedStatement(
            path=path, parser_name=self.name, institution="Venmo", account="Venmo",
            statement_id=statement_id, period_start=start, period_end=end,
            transactions=transactions, source_sha256=source_hash,
        )


def _amount(raw):
    match = _AMOUNT.match(raw.strip())
    if not match:
        return Decimal("0.00")
    value = money(match.group(2))
    return -value if match.group(1) == "-" else value


def _description(kind, who_from, who_to, note):
    if kind == "Standard Transfer":
        return "Venmo Standard Transfer to bank"
    parties = f"{who_from} -> {who_to}" if (who_from or who_to) else "Venmo"
    return f"{kind} {parties}" + (f": {note}" if note else "")
