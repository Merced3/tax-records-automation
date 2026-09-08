"""Cash App monthly PDF parser."""

from collections import Counter
from datetime import date
import calendar
import re

import pdfplumber

from .base import StatementParser
from ..models import ParsedStatement, Transaction, digest, money
from ..safety import sha256_file

_MONTHS = {name: i for i, name in enumerate(calendar.month_abbr) if name}
_MONTH_PATTERN = "|".join(_MONTHS)
_HEADER_RE = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$", re.M)
_TXN_RE = re.compile(rf"^(({_MONTH_PATTERN})\s+\d{{1,2}})\s+(.+?)\s+\$([\d,]+\.\d{{2}})\s+(\+?)\s*\$([\d,]+\.\d{{2}})\s*$")
_DETAILS = ("Cash App payment", "Instant transfer", "Standard transfer", "Card payment")


class CashAppParser(StatementParser):
    name = "cashapp"

    def can_parse(self, first_page_text, path):
        return "Account Statement" in first_page_text and "Cash App" in first_page_text

    def parse(self, path, account, fallback_year):
        with pdfplumber.open(path) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return self.parse_pages(pages, str(path), account, fallback_year,
                                sha256_file(path))

    def parse_pages(self, pages, path, account, fallback_year, source_hash="synthetic"):
        header = _HEADER_RE.search(pages[0])
        if not header:
            raise ValueError("Cash App statement month/year not found")
        full_month, year_text = header.groups()
        month = list(calendar.month_name).index(full_month)
        year = int(year_text)
        period_start = date(year, month, 1)
        period_end = date(year, month, calendar.monthrange(year, month)[1])
        statement_id = digest("cashapp", account, period_start, period_end)

        rows = []
        in_transactions = False
        for page_number, text in enumerate(pages, 1):
            for line_number, raw in enumerate(text.splitlines(), 1):
                line = raw.strip()
                if line == "Transactions":
                    in_transactions = True
                    continue
                if line.startswith("All transactions shown"):
                    in_transactions = False
                    continue
                if not in_transactions or line.startswith("Date Description"):
                    continue
                match = _TXN_RE.match(line)
                if match:
                    date_text, month_name, description, fee, plus, amount = match.groups()
                    rows.append((date_text, month_name, description, fee, plus,
                                 amount, page_number, line_number))

        transactions = []
        occurrences = Counter()
        for date_text, month_name, description, fee, plus, amount, page, line in rows:
            day = int(date_text.split()[1])
            txn_date = date(year, _MONTHS[month_name], day)
            signed = money(amount) if plus else -money(amount)
            key = (txn_date, signed, description, money(fee))
            occurrences[key] += 1
            merchant = description
            for suffix in _DETAILS:
                if merchant.endswith(suffix):
                    merchant = merchant[:-len(suffix)].strip()
                    break
            txn = Transaction(
                institution="Cash App", account=account, statement_id=statement_id,
                date=txn_date, amount=signed, raw_description=description,
                merchant=merchant or description, source_file=path,
                source_page=page, source_line=line, fee=money(fee),
                occurrence=occurrences[key],
            )
            txn.assign_id()
            transactions.append(txn)

        return ParsedStatement(
            path=path, parser_name=self.name, institution="Cash App", account=account,
            statement_id=statement_id, period_start=period_start,
            period_end=period_end, transactions=transactions,
            source_sha256=source_hash,
        )
