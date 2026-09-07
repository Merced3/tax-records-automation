"""Reconciliation audit — prove the extraction, don't eyeball it.

Two proofs:

1. Chase, per account: a year's statements should chain into consecutive
   periods (each starts shortly after the previous ends). Small gaps are
   normal — statements open a few days into a cycle. But an OVERLAP between
   consecutive periods means duplicated statement files, which is where
   duplicate transactions come from. Per-account because each account has
   its own statement cycle.

2. Cash App, per year: the sum of all parsed transactions must equal the
   sum of (ending - beginning) balance across every statement. Clean
   calendar months make this exact — a mismatch means missing or extra
   transactions, full stop.

Money is compared in integer cents; float dust never causes false alarms.
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime

import pdfplumber

# ----------------------------- money ---------------------------------

def cents(s):
    """'1,234.56' / '-12.00' / '+ 4.00' (no $ signs) -> integer cents."""
    s = s.replace(",", "").replace("$", "").replace("+", "").strip()
    neg = s.startswith("-")
    s = s.lstrip("-").strip()
    dollars_, _, c = s.partition(".")
    v = int(dollars_ or 0) * 100 + int(c or 0)
    return -v if neg else v


def dollars(c):
    return f"${c/100:,.2f}"


# ----------------------------- chase ---------------------------------

_MONTH = "January|February|March|April|May|June|July|August|September|October|November|December"
# Newer statements insert a legal notice on page 1 and use spaces around
# "through"; older ones don't. Read enough pages to find both the period
# and the balance summary.
CHASE_PERIOD_RE = re.compile(
    rf"({_MONTH})\s+(\d{{1,2}}),\s+(\d{{4}})\s*through\s*({_MONTH})\s+(\d{{1,2}}),\s+(\d{{4}})"
)
# Chase prints negatives as -$12.00, positives as $12.00.
CHASE_BEGIN_RE = re.compile(r"Beginning Balance (-?)\$([\d,]+\.\d{2})")
CHASE_END_RE = re.compile(r"Ending Balance (-?)\$([\d,]+\.\d{2})")

_MONTH_NUM = {m: i + 1 for i, m in enumerate(
    "January February March April May June July August September October November December".split())}


@dataclass
class ChaseStatement:
    path: str
    start: datetime
    end: datetime


def read_chase_summary(path):
    with pdfplumber.open(path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
    per = CHASE_PERIOD_RE.search(text)
    if not per:
        raise ValueError("no statement period found")
    sm, sd, sy, em, ed, ey = per.groups()
    if not (CHASE_BEGIN_RE.search(text) and CHASE_END_RE.search(text)):
        raise ValueError("no balance summary found")
    return ChaseStatement(
        path=path,
        start=datetime(int(sy), _MONTH_NUM[sm], int(sd)),
        end=datetime(int(ey), _MONTH_NUM[em], int(ed)),
    )


# ----------------------------- cashapp --------------------------------

CA_MONEY_IN_RE = re.compile(r"Money In \+ \$([\d,]+\.\d{2})")
CA_MONEY_OUT_RE = re.compile(r"Money Out - \$([\d,]+\.\d{2})")


@dataclass
class CashAppStatement:
    path: str
    in_cents: int
    out_cents: int


def read_cashapp_summary(path):
    """Compare against the printed Money In / Money Out lines, not the
    balance delta: instant-transfer fees live in their own column and don't
    appear in either, so balance math would falsely flag fee months."""
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""
    mi, mo = CA_MONEY_IN_RE.search(text), CA_MONEY_OUT_RE.search(text)
    if not (mi or mo):
        raise ValueError("no Money In/Out lines found")
    # A line is omitted when it's $0.00.
    return CashAppStatement(path=path,
                            in_cents=cents(mi.group(1)) if mi else 0,
                            out_cents=cents(mo.group(1)) if mo else 0)


# ----------------------------- the audit ------------------------------

@dataclass
class AuditResult:
    label: str
    checks: list = field(default_factory=list)  # (ok, message)

    @property
    def ok(self):
        return all(ok for ok, _ in self.checks)


def _account_of(path):
    return os.path.basename(os.path.dirname(path))


def audit_chase(paths):
    """Per-account statement chaining. Returns AuditResult."""
    res = AuditResult("Chase")
    by_account = {}
    for p in paths:
        try:
            by_account.setdefault(_account_of(p), []).append(read_chase_summary(p))
        except Exception as e:
            res.checks.append((False, f"summary unreadable: "
                                      f"{_account_of(p)}/{os.path.basename(p)}: {e}"))

    for account, stmts in sorted(by_account.items()):
        stmts.sort(key=lambda s: s.start)
        problems = []
        for a, b in zip(stmts, stmts[1:]):
            overlap = (a.end - b.start).days
            if overlap > 0:
                problems.append(f"{os.path.basename(a.path)} ends {a.end:%m/%d} "
                                f"but {os.path.basename(b.path)} starts {b.start:%m/%d} "
                                f"({overlap}d overlap)")
        res.checks.append((not problems,
                           f"{account}: {len(stmts)} statements chain consecutively"
                           + ("" if not problems else " — " + "; ".join(problems))))
    return res


def audit_cashapp(paths, transactions):
    res = AuditResult("Cash App")
    stmts = []
    for p in paths:
        try:
            stmts.append(read_cashapp_summary(p))
        except ValueError as e:
            if "no Money In/Out" in str(e):
                # Month prints no summary when a line is $0.00 — count zeros.
                stmts.append(CashAppStatement(path=p, in_cents=0, out_cents=0))
                continue
            res.checks.append((False, f"summary unreadable: {os.path.basename(p)}: {e}"))

    exp_in = sum(s.in_cents for s in stmts)
    exp_out = sum(s.out_cents for s in stmts)
    got_in = int(round(sum(t.amount for t in transactions if t.amount > 0) * 100))
    got_out = int(round(sum(-t.amount for t in transactions if t.amount < 0) * 100))

    # Payments funded directly from the linked bank ("To X from Chase Bank")
    # never touch the Cash App balance, so they're excluded from Money
    # In/Out. Subtract them before comparing.
    direct_out = int(round(sum(-t.amount for t in transactions
                               if t.amount < 0 and " from " in t.description.lower()) * 100))
    adj_out = got_out - direct_out

    res.checks.append((exp_in == got_in,
                       f"money in: extracted {dollars(got_in)} == statements' {dollars(exp_in)}"
                       + ("" if exp_in == got_in else " — MISMATCH")))
    res.checks.append((exp_out == adj_out,
                       f"money out: extracted {dollars(got_out)} - bank-funded {dollars(direct_out)} "
                       f"= {dollars(adj_out)} == statements' {dollars(exp_out)}"
                       + ("" if exp_out == adj_out else " — MISMATCH")))
    return res
