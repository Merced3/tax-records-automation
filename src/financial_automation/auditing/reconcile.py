"""Independent reconciliation checks against statement summaries."""

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
    cashapp = [s for s in pipeline_report.statements if s.parser_name == "cashapp"]
    if chase:
        _audit_chase(result, chase)
    if cashapp:
        _audit_cashapp(result, cashapp)
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
