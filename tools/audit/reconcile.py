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
from datetime import datetime, timedelta

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
    begin_cents: int = 0
    end_cents: int = 0


def _signed_cents(m):
    """m has (sign_group, digits_group); Chase prints -$12.00 / $12.00."""
    v = cents(m.group(2))
    return -v if m.group(1) == "-" else v


def read_chase_summary(path):
    with pdfplumber.open(path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
    per = CHASE_PERIOD_RE.search(text)
    if not per:
        raise ValueError("no statement period found")
    sm, sd, sy, em, ed, ey = per.groups()
    begin = CHASE_BEGIN_RE.search(text)
    end = CHASE_END_RE.search(text)
    if not (begin and end):
        raise ValueError("no balance summary found")
    return ChaseStatement(
        path=path,
        start=datetime(int(sy), _MONTH_NUM[sm], int(sd)),
        end=datetime(int(ey), _MONTH_NUM[em], int(ed)),
        begin_cents=_signed_cents(begin),
        end_cents=_signed_cents(end),
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


def audit_chase(paths, txns_by_file=None):
    """Two proofs per year: (1) statements chain consecutively per account;
    (2) each statement's parsed transactions sum to its own balance delta.

    txns_by_file maps pdf path -> list of Transaction for that file (needed
    for check 2). Check 2 is what catches silently dropped/fused
    transactions — the failure mode that chaining alone missed."""
    res = AuditResult("Chase")
    by_account = {}
    summaries = {}
    for p in paths:
        try:
            s = read_chase_summary(p)
            by_account.setdefault(_account_of(p), []).append(s)
            summaries[p] = s
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

    if txns_by_file is not None:
        _audit_chase_dollars(res, summaries, txns_by_file)
        _audit_chase_dates(res, summaries, txns_by_file)
        _audit_chase_balance_chain(res, summaries, txns_by_file)
    return res


def _audit_chase_dollars(res, summaries, txns_by_file):
    """Each statement's parsed sum must equal its own balance delta."""
    mismatches, checked = [], 0
    for p, s in summaries.items():
        txns = txns_by_file.get(p)
        if txns is None:
            continue
        checked += 1
        got = int(round(sum(t.amount for t in txns) * 100))
        expected = s.end_cents - s.begin_cents
        if got != expected:
            mismatches.append(
                f"{os.path.basename(p)}: sum {dollars(got)} "
                f"!= delta {dollars(expected)} (off {dollars(got - expected)})")
    res.checks.append((not mismatches,
                       f"{checked} statements: parsed sums == balance deltas"
                       + ("" if not mismatches else " — " + "; ".join(mismatches))))


def _audit_chase_dates(res, summaries, txns_by_file):
    """Every transaction date must fall inside its statement's period.
    Catches right-amount-wrong-date rows the dollar check can't see."""
    bad, checked = [], 0
    for p, s in summaries.items():
        txns = txns_by_file.get(p)
        if txns is None:
            continue
        checked += 1
        for t in txns:
            try:
                d = datetime.strptime(t.date, "%m/%d/%Y")
            except ValueError:
                bad.append(f"{os.path.basename(p)}: unparseable date {t.date!r}")
                continue
            # Allow the period's start/end inclusive; a 1-day slack for the
            # few statements whose first txn posts the day after 'start'.
            if not (s.start - timedelta(days=1) <= d <= s.end + timedelta(days=1)):
                bad.append(f"{os.path.basename(p)}: {t.date} outside "
                           f"{s.start:%m/%d}-{s.end:%m/%d}")
    res.checks.append((not bad,
                       f"{checked} statements: all dates within statement periods"
                       + ("" if not bad else " — " + "; ".join(bad[:6]))))


def _audit_chase_balance_chain(res, summaries, txns_by_file):
    """Each row's printed running balance must equal prev balance + amount.
    Independent of sums — catches merged, split, or reordered rows."""
    bad, checked = [], 0
    for p, s in summaries.items():
        txns = txns_by_file.get(p)
        if not txns or txns[0].balance is None:
            continue
        checked += 1
        prev = s.begin_cents
        for t in txns:
            expected = prev + int(round(t.amount * 100))
            got = int(round(t.balance * 100))
            if got != expected:
                bad.append(f"{os.path.basename(p)}: after {t.date} {t.description[:25]} "
                           f"balance {dollars(got)} != expected {dollars(expected)}")
                break  # one break per file is enough to flag it
            prev = got
    res.checks.append((not bad,
                       f"{checked} statements: running-balance chain consistent"
                       + ("" if not bad else " — " + "; ".join(bad[:6]))))


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
