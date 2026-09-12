"""Independent reconciliation checks against statement summaries."""

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import re

import pdfplumber

from ..models import ParsedStatement, money


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class AuditReport:
    year: int
    checks: list = field(default_factory=list)

    @property
    def passed(self):
        return bool(self.checks) and all(c.passed for c in self.checks)

    def add(self, name, passed, detail):
        self.checks.append(Check(name, passed, detail))

    def as_dict(self):
        return {"year": self.year, "passed": self.passed,
                "checks": [c.__dict__ for c in self.checks]}


_BEGIN = re.compile(r"Beginning Balance (-?)\$([\d,]+\.\d{2})")
_END = re.compile(r"Ending Balance (-?)\$([\d,]+\.\d{2})")
_MONEY_IN = re.compile(r"Money In \+ \$([\d,]+\.\d{2})")
_MONEY_OUT = re.compile(r"Money Out - \$([\d,]+\.\d{2})")
_CHANGE = re.compile(r"\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})")


def _signed(match):
    value = money(match.group(2))
    return -value if match.group(1) == "-" else value


def _pages(path, count=None):
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages if count is None else pdf.pages[:count]
        return [p.extract_text() or "" for p in pages]


def audit(year, pipeline_report):
    result = AuditReport(int(year))
    if pipeline_report.errors:
        result.add("ingestion errors", False, f"{len(pipeline_report.errors)} error(s)")
    if pipeline_report.unclaimed_files:
        result.add("unclaimed PDFs", False, f"{len(pipeline_report.unclaimed_files)} unclaimed")
    result.add("source accounting", not pipeline_report.errors and not pipeline_report.unclaimed_files,
               f"{len(pipeline_report.statements)} parsed; "
               f"{len(pipeline_report.ignored_files)} explicitly ignored")

    chase = [s for s in pipeline_report.statements if s.parser_name == "chase"]
    credit = [s for s in pipeline_report.statements if s.parser_name == "chase-credit"]
    cashapp = [s for s in pipeline_report.statements if s.parser_name == "cashapp"]
    if chase:
        _audit_chase(result, chase)
    if credit:
        _audit_chase_credit(result, credit)
    if cashapp:
        _audit_cashapp(result, cashapp)
    venmo = [s for s in pipeline_report.statements if s.parser_name == "venmo"]
    if venmo:
        _audit_venmo(result, venmo)
    return result


def _audit_chase(result, statements):
    by_account = defaultdict(list)
    for statement in statements:
        by_account[statement.account].append(statement)
    problems = []
    for account, rows in by_account.items():
        rows.sort(key=lambda s: s.period_start)
        for left, right in zip(rows, rows[1:]):
            overlap = (left.period_end - right.period_start).days
            if overlap > 0:
                problems.append(f"{account}: {Path(left.path).name}/{Path(right.path).name} overlap {overlap}d")
    result.add("Chase statement sequence", not problems,
               f"{len(statements)} statements" if not problems else "; ".join(problems))

    sum_bad, date_bad, chain_bad = [], [], []
    for statement in statements:
        text = "\n".join(_pages(statement.path, 2))
        begin, end = _BEGIN.search(text), _END.search(text)
        if not (begin and end):
            sum_bad.append(f"{Path(statement.path).name}: summary unreadable")
            continue
        beginning, ending = _signed(begin), _signed(end)
        rows = statement.transactions
        parsed_sum = sum((t.amount for t in rows), Decimal("0.00"))
        if parsed_sum != ending - beginning:
            sum_bad.append(f"{Path(statement.path).name}: {parsed_sum} != {ending-beginning}")
        for txn in rows:
            if not (statement.period_start <= txn.date <= statement.period_end):
                date_bad.append(f"{Path(statement.path).name}: {txn.date}")
        previous = beginning
        for txn in rows:
            if txn.balance is None or previous + txn.amount != txn.balance:
                chain_bad.append(f"{Path(statement.path).name}: page {txn.source_page} line {txn.source_line}")
                break
            previous = txn.balance
        # Empty statements are checked, not skipped.
        if not rows and beginning != ending:
            chain_bad.append(f"{Path(statement.path).name}: empty parse but non-zero delta")

    result.add("Chase statement sums", not sum_bad,
               f"{len(statements)} statements reconcile" if not sum_bad else "; ".join(sum_bad[:8]))
    result.add("Chase transaction dates", not date_bad,
               "all dates inside periods" if not date_bad else "; ".join(date_bad[:8]))
    result.add("Chase running balances", not chain_bad,
               "every row chains" if not chain_bad else "; ".join(chain_bad[:8]))


def _venmo_money(raw):
    raw = (raw or "").strip()
    if not raw:
        return Decimal("0.00")
    digits = re.sub(r"[^0-9.]", "", raw)
    if not digits:
        return Decimal("0.00")
    value = money(digits)
    return -value if "-" in raw else value


def _audit_venmo(result, statements):
    """Venmo exports print beginning/ending balances and, per row, the funding
    source and destination. That is an independent arithmetic relationship:

        ending = beginning + (money into the Venmo balance)
                           + (money out funded by the Venmo balance)

    Card-funded payments never touch the balance, so they must be excluded.
    This is re-derived straight from the file, not from parser output, and it
    also proves parsed row identity/count against the file's own IDs.
    """
    balance_bad, count_bad, date_bad, id_bad = [], [], [], []
    for statement in statements:
        name = Path(statement.path).name
        with open(statement.path, encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.reader(io.StringIO(f.read())))
        header_at = next((i for i, r in enumerate(rows)
                          if r[1:3] == ["ID", "Datetime"]), None)
        if header_at is None:
            count_bad.append(f"{name}: no transaction header")
            continue
        beginning = ending = Decimal("0.00")
        delta = Decimal("0.00")
        file_ids = []
        for row in rows[header_at + 1:]:
            if len(row) < 18:
                continue
            if not row[1].strip():
                if row[16].strip():
                    beginning = _venmo_money(row[16])
                if row[17].strip():
                    ending = _venmo_money(row[17])
                continue
            if row[4].strip() not in ("Complete", "Issued"):
                continue
            file_ids.append(row[1].strip())
            amount = _venmo_money(row[8])
            funding, destination = row[14].strip(), row[15].strip()
            if amount > 0:
                if destination in ("Venmo balance", ""):
                    delta += amount
            elif funding in ("Venmo balance", ""):
                delta += amount
        if beginning + delta != ending:
            balance_bad.append(f"{name}: {beginning}+{delta} != {ending}")
        parsed_ids = [t.provider_id for t in statement.transactions]
        if len(parsed_ids) != len(file_ids):
            count_bad.append(f"{name}: parsed {len(parsed_ids)}/{len(file_ids)}")
        if sorted(parsed_ids) != sorted(file_ids):
            id_bad.append(name)
        for txn in statement.transactions:
            if not (statement.period_start <= txn.date <= statement.period_end):
                date_bad.append(f"{name}: {txn.date}")
    result.add("Venmo balance chain", not balance_bad,
               f"{len(statements)} files reconcile beginning->ending balance"
               if not balance_bad else "; ".join(balance_bad[:8]))
    result.add("Venmo row completeness", not count_bad,
               f"{len(statements)} files reconcile" if not count_bad else "; ".join(count_bad[:8]))
    result.add("Venmo provider IDs", not id_bad,
               "parsed IDs match file IDs" if not id_bad else "; ".join(id_bad[:8]))
    result.add("Venmo transaction dates", not date_bad,
               "all dates inside file spans" if not date_bad else "; ".join(date_bad[:8]))


def _audit_chase_credit(result, statements):
    labels = ["Previous Balance", "Payment, Credits", "Purchases", "Cash Advances",
              "Balance Transfers", "Fees Charged", "Interest Charged", "New Balance"]
    sum_bad, date_bad, seq_bad = [], [], []
    by_account = defaultdict(list)
    for statement in statements:
        by_account[statement.account].append(statement)
    for account, rows in by_account.items():
        rows.sort(key=lambda s: s.period_start)
        for left, right in zip(rows, rows[1:]):
            if (left.period_end - right.period_start).days > 0:
                seq_bad.append(f"{account}: {Path(left.path).name}/{Path(right.path).name}")
    for statement in statements:
        text = "\n".join(_pages(statement.path, 2)).replace("`", "")
        values = {}
        for label in labels:
            found = re.search(rf"{label}\s+([+-]?)\$([\d,]+\.\d{{2}})", text)
            if not found:
                sum_bad.append(f"{Path(statement.path).name}: '{label}' unreadable")
                values = None
                break
            sign = Decimal("-1") if found.group(1) == "-" else Decimal("1")
            values[label] = sign * money(found.group(2))
        if values is None:
            continue
        coupons = values["Purchases"] + values["Cash Advances"] + values["Balance Transfers"] + \
                  values["Fees Charged"] + values["Interest Charged"]
        rows = statement.transactions
        if (values["Previous Balance"] + values["Payment, Credits"] + coupons
                != values["New Balance"]):
            sum_bad.append(f"{Path(statement.path).name}: summary identity broken")
            continue
        parsed_credit = sum((t.amount for t in rows if t.amount > 0), Decimal("0.00"))
        parsed_debit = sum((-t.amount for t in rows if t.amount < 0), Decimal("0.00"))
        if parsed_credit != -values["Payment, Credits"] or parsed_debit != coupons:
            sum_bad.append(f"{Path(statement.path).name}: {parsed_credit}/{-values['Payment, Credits']}, {parsed_debit}/{coupons}")
        for txn in rows:
            # Chase lists transactions posted a few days before the printed
            # opening date (posting lag vs. cycle boundary).
            if not (statement.period_start - timedelta(days=3) <= txn.date
                    <= statement.period_end):
                date_bad.append(f"{Path(statement.path).name}: {txn.date}")
    result.add("Chase credit summary identity",
               not seq_bad and not sum_bad,
               f"{len(statements)} statements reconcile" if not seq_bad and not sum_bad else
               "; ".join((seq_bad + sum_bad)[:8]))
    result.add("Chase credit transaction dates", not date_bad,
               "all dates inside periods" if not date_bad else "; ".join(date_bad[:8]))


def _audit_cashapp(result, statements):
    summary_bad, date_bad = [], []
    for statement in statements:
        text = _pages(statement.path, 1)[0]
        mi, mo = _MONEY_IN.search(text), _MONEY_OUT.search(text)
        change = _CHANGE.search(text)
        expected_in = money(mi.group(1)) if mi else Decimal("0.00")
        expected_out = money(mo.group(1)) if mo else Decimal("0.00")
        if not (mi or mo) and change and money(change.group(2)) != Decimal("0.00"):
            summary_bad.append(f"{Path(statement.path).name}: missing summaries with non-zero change")
        rows = statement.transactions
        actual_in = sum((t.amount for t in rows if t.amount > 0), Decimal("0.00"))
        direct = sum((-t.amount for t in rows if t.amount < 0 and " from " in t.raw_description.lower()), Decimal("0.00"))
        actual_out = sum((-t.amount for t in rows if t.amount < 0), Decimal("0.00")) - direct
        if actual_in != expected_in or actual_out != expected_out:
            summary_bad.append(f"{Path(statement.path).name}: in {actual_in}/{expected_in}, out {actual_out}/{expected_out}")
        for txn in rows:
            if not (statement.period_start <= txn.date <= statement.period_end):
                date_bad.append(f"{Path(statement.path).name}: {txn.date}")
    result.add("Cash App monthly totals", not summary_bad,
               f"{len(statements)} statements reconcile" if not summary_bad else "; ".join(summary_bad[:8]))
    result.add("Cash App transaction dates", not date_bad,
               "all dates inside statement months" if not date_bad else "; ".join(date_bad[:8]))
