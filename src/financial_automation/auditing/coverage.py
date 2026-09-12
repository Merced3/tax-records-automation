"""Evidence-period coverage: which days of the year do statements cover?

Coverage is a different question from extraction accuracy. Every statement can
reconcile perfectly while whole months of an account are simply absent, and an
account with no discovered files produces no failing check at all. Empty
discovery is not successful financial coverage.

Coverage is derived ONLY from printed statement periods, never from filenames.
Known-unavailable history (for example an account the owner can no longer
access) is declared in config/app.yaml as `known_coverage_gaps` so it is
reported as a disclosed limitation instead of silently looking complete.

Statement cycles cross calendar years, so coverage of December depends on the
NEXT year's January statement. Adjacent-year statements are therefore included
when measuring a year's covered days; otherwise every year would report a
false late-December gap.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class AccountCoverage:
    institution: str
    account: str
    statements: int = 0
    covered_days: int = 0
    year_days: int = 0
    gaps: list = field(default_factory=list)      # (start, end) inside the year
    first: date = None
    last: date = None
    # True when no statement for this account prints its own period, so day
    # coverage is unmeasurable rather than zero (Venmo exports).
    period_unmeasurable: bool = False

    @property
    def percent(self):
        return 0.0 if not self.year_days else 100.0 * self.covered_days / self.year_days


@dataclass
class CoverageReport:
    year: int
    accounts: list = field(default_factory=list)
    known_gaps: list = field(default_factory=list)   # declared, with reasons
    undeclared_gap_days: int = 0

    @property
    def complete(self):
        """True only when every measurable account covers the whole year and
        nothing is declared missing or unmeasurable. Deliberately strict: it
        is the honest answer to 'do we have all the records?'"""
        return (bool(self.accounts)
                and not self.known_gaps
                and all(not a.gaps and not a.period_unmeasurable
                        for a in self.accounts))


def _merge(periods):
    merged = []
    for start, end in sorted(periods):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def coverage(year, pipeline_report, known_gaps=None, adjacent_statements=()):
    """`adjacent_statements` are statements discovered under other years'
    folders (typically year-1 and year+1). They contribute covered days but
    are not counted as this year's statements."""
    year = int(year)
    jan1, dec31 = date(year, 1, 1), date(year, 12, 31)
    report = CoverageReport(year)

    by_account = defaultdict(list)
    own = set()
    for statement in pipeline_report.statements:
        key = (statement.institution, statement.account)
        by_account[key].append(statement)
        own.add(id(statement))
    for statement in adjacent_statements:
        key = (statement.institution, statement.account)
        if key in by_account:
            by_account[key].append(statement)

    for (institution, account), statements in sorted(by_account.items()):
        printed = [s for s in statements if s.period_source == "printed"]
        periods = []
        for statement in printed:
            # Clip to the calendar year: a January statement legitimately
            # covers part of the prior December.
            start = max(statement.period_start, jan1)
            end = min(statement.period_end, dec31)
            if start <= end:
                periods.append((start, end))
        entry = AccountCoverage(institution, account,
                                sum(1 for s in statements if id(s) in own),
                                year_days=(dec31 - jan1).days + 1)
        if not printed:
            # No statement states its own period: report the observed activity
            # span and say coverage is unmeasurable instead of inventing gaps.
            dates = [t.date for s in statements for t in s.transactions
                     if jan1 <= t.date <= dec31]
            entry.period_unmeasurable = True
            if dates:
                entry.first, entry.last = min(dates), max(dates)
            report.accounts.append(entry)
            continue
        merged = _merge(periods)
        if merged:
            entry.first, entry.last = merged[0][0], merged[-1][1]
            entry.covered_days = sum((e - s).days + 1 for s, e in merged)
            cursor = jan1
            for start, end in merged:
                if start > cursor:
                    entry.gaps.append((cursor, start - timedelta(days=1)))
                cursor = max(cursor, end + timedelta(days=1))
            if cursor <= dec31:
                entry.gaps.append((cursor, dec31))
        else:
            entry.gaps.append((jan1, dec31))
        report.accounts.append(entry)

    for gap in (known_gaps or []):
        if int(gap.get("year", year)) != year:
            continue
        report.known_gaps.append(gap)

    declared_accounts = {g.get("account") for g in report.known_gaps}
    declared_institutions = {g.get("institution") for g in report.known_gaps}
    for entry in report.accounts:
        if entry.account in declared_accounts or entry.institution in declared_institutions:
            continue
        if entry.period_unmeasurable:
            continue
        report.undeclared_gap_days += sum((e - s).days + 1 for s, e in entry.gaps)
    return report
