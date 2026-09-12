"""Venmo monthly CSV statement parser.

Venmo exports print no Money In/Out summary, but they do print beginning and
ending balances, and each row names its funding source and destination. That
supports a real arithmetic check (see auditing.reconcile._audit_venmo), not
only a row count.

Rows are kept when the transfer actually moved money: `Complete`, and
`Issued` standard bank transfers. Other statuses (cancelled/failed/returned)
are counted and reported rather than silently dropped.

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
KEPT_STATUSES = {"Complete", "Issued"}
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
        seen_ids = set()
        skipped = Counter()
        dates = []
        for index, row in enumerate(rows[header_at + 1:], header_at + 2):
            if len(row) < 9 or not (row[1].strip().isdigit() and row[2].strip()):
                continue  # balance filler row and disclaimer footer
            row_id, when, kind, status = row[1], row[2], row[3], row[4]
            if status.strip() not in KEPT_STATUSES:
                skipped[status.strip() or "(blank)"] += 1
                continue
            amount = _amount(row[8], path, index)
            txn_date = datetime.fromisoformat(when.strip()).date()
            dates.append(txn_date)
            note = row[5].strip()
            who_from = row[6].strip()
            who_to = row[7].strip()
            description = _description(kind, who_from, who_to, note)
            base = (txn_date.isoformat(), amount, description)
            occurrence[base] += 1
            provider_id = row_id.strip()
            if provider_id in seen_ids:
                raise ValueError(f"{path} line {index}: duplicate Venmo ID {provider_id}")
            seen_ids.add(provider_id)
            txn = Transaction(
                provider_id=provider_id,
                institution="Venmo", account="Venmo",
                statement_id="",  # filled after period is known
                date=txn_date, amount=amount, raw_description=description,
                merchant=description, source_file=path,
                source_page=1, source_line=index,
                occurrence=occurrence[base],
                fee=_fee(row[11]),
                metadata={"status": status.strip(),
                          "funding_source": row[14].strip(),
                          "destination": row[15].strip()},
            )
            transactions.append(txn)

        if not dates:
            start = end = datetime(fallback_year, 1, 1).date()
        else:
            start, end = min(dates), max(dates)
        # Statement identity is content-derived (period + row IDs), never the
        # file path: moving or renaming an export must not change identity.
        statement_id = digest("venmo", start, end,
                              *sorted(t.provider_id for t in transactions))
        for txn in transactions:
            txn.statement_id = statement_id
            txn.assign_id()

        return ParsedStatement(
            path=path, parser_name=self.name, institution="Venmo", account="Venmo",
            statement_id=statement_id, period_start=start, period_end=end,
            transactions=transactions, source_sha256=source_hash,
            # Venmo exports print no statement period; this span is derived
            # from the rows themselves and cannot establish day coverage.
            period_source="derived",
            metadata={"skipped_statuses": dict(skipped)},
        )


def _amount(raw, path="", line=0):
    """Strict: a malformed amount is an ingestion error, never 0.00.

    Silently zeroing an unparsable amount produced rows that reconciled
    against a row count while misstating money.
    """
    match = _AMOUNT.match(raw.strip())
    if not match:
        raise ValueError(f"{path} line {line}: unparsable Venmo amount {raw!r}")
    value = money(match.group(2))
    return -value if match.group(1) == "-" else value


def _fee(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    match = _AMOUNT.match(raw)
    if not match:
        raise ValueError(f"unparsable Venmo fee {raw!r}")
    value = money(match.group(2))
    return -value if match.group(1) == "-" else value


def _description(kind, who_from, who_to, note):
    if kind == "Standard Transfer":
        return "Venmo Standard Transfer to bank"
    parties = f"{who_from} -> {who_to}" if (who_from or who_to) else "Venmo"
    return f"{kind} {parties}" + (f": {note}" if note else "")
