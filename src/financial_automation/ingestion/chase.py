"""Chase statement parser with regression-tested page-boundary recovery."""

from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
import re

import pdfplumber

from .base import StatementParser
from ..models import ParsedStatement, Transaction, digest, money
from ..safety import sha256_file

_MONTHS = "January February March April May June July August September October November December".split()
_MONTH_PATTERN = "|".join(_MONTHS)
_MONTH_NUMBER = {name: i + 1 for i, name in enumerate(_MONTHS)}
_PERIOD_RE = re.compile(rf"({_MONTH_PATTERN})\s+(\d{{1,2}}),\s+(\d{{4}})\s*through\s*({_MONTH_PATTERN})\s+(\d{{1,2}}),\s+(\d{{4}})")
_TXN_RE = re.compile(r"^(\d{2}/\d{2})\s+(.+?)\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})\s*$")
_FUSED_DATE = re.compile(r"transac(\d)tion\s+detail(\d/\d{2})", re.I)
_SKIP = ("Beginning Balance", "Ending Balance", "(continued)", "TRANSACTION", "Account Number", "DATE")
_MERCHANT_PATTERNS = [
    r"^(Recurring )?Card Purchase( With Pin)? \d{2}/\d{2} ",
    r"^Payment Received \d{2}/\d{2} ", r"^\d{2}/\d{2} ",
    r"\s+Card \d+$", r"\s+(Web|CCD) ID:.*$",
]


def clean_merchant(description):
    value = description
    for pattern in _MERCHANT_PATTERNS:
        value = re.sub(pattern, "", value)
    return value.strip(" -") or description


class ChaseParser(StatementParser):
    name = "chase"

    def can_parse(self, first_page_text, path):
        return "JPMorgan Chase Bank" in first_page_text

    def parse(self, path, account, fallback_year):
        with pdfplumber.open(path) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return self.parse_pages(pages, str(path), account, fallback_year,
                                sha256_file(path))

    def parse_pages(self, pages, path, account, fallback_year, source_hash="synthetic"):
        period = self._period("\n".join(pages[:2]), fallback_year)
        statement_id = digest("chase", account, period[0], period[1])
        raw_rows = []
        in_detail = False

        for page_number, text in enumerate(pages, 1):
            for line_number, raw in enumerate(text.splitlines(), 1):
                line = raw.strip()
                squashed = line.replace(" ", "").lower()
                if "*start*transactiondetail" in squashed:
                    in_detail = True
                    continue
                if "*end*transac" in squashed:
                    recovered = self._recover_fused(line)
                    if in_detail and recovered:
                        recovered.update(page=page_number, line=line_number)
                        raw_rows.append(recovered)
                    in_detail = False
                    continue
                if not in_detail or not line or line.startswith(_SKIP):
                    continue
                match = _TXN_RE.match(line)
                if match:
                    mmdd, description, amount, balance = match.groups()
                    raw_rows.append({"mmdd": mmdd, "description": description,
                                     "amount": amount, "balance": balance,
                                     "page": page_number, "line": line_number})
                elif raw_rows and not line.startswith("Page"):
                    raw_rows[-1]["description"] += " " + line

        transactions = []
        occurrence_counts = Counter()
        for row in raw_rows:
            txn_date = self._transaction_date(row["mmdd"], period)
            identity_base = (txn_date.isoformat(), money(row["amount"]),
                             row["description"], money(row["balance"]))
            occurrence_counts[identity_base] += 1
            txn = Transaction(
                institution="Chase", account=account, statement_id=statement_id,
                date=txn_date, amount=money(row["amount"]),
                raw_description=row["description"],
                merchant=clean_merchant(row["description"]), source_file=path,
                source_page=row["page"], source_line=row["line"],
                balance=money(row["balance"]),
                occurrence=occurrence_counts[identity_base],
            )
            txn.assign_id()
            transactions.append(txn)

        return ParsedStatement(
            path=path, parser_name=self.name, institution="Chase", account=account,
            statement_id=statement_id, period_start=period[0], period_end=period[1],
            transactions=transactions, source_sha256=source_hash,
        )

    @staticmethod
    def _period(text, fallback_year):
        match = _PERIOD_RE.search(text)
        if not match:
            raise ValueError("Chase statement period not found")
        sm, sd, sy, em, ed, ey = match.groups()
        return (date(int(sy), _MONTH_NUMBER[sm], int(sd)),
                date(int(ey), _MONTH_NUMBER[em], int(ed)))

    @staticmethod
    def _transaction_date(mmdd, period):
        month, day = map(int, mmdd.split("/"))
        start, end = period
        year = start.year if start.year != end.year and month == 12 else end.year
        return date(year, month, day)

    @staticmethod
    def _recover_fused(line):
        match = _FUSED_DATE.search(line)
        if not match:
            return None
        mmdd = match.group(1) + match.group(2)
        tail = line[match.end():].strip()
        row = re.match(r"^(.+?)\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})\s*$", tail)
        if not row:
            return None
        description, amount, balance = row.groups()
        return {"mmdd": mmdd, "description": description,
                "amount": amount, "balance": balance}
