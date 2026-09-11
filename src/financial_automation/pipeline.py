"""Source discovery and bank-agnostic ingestion pipeline."""

from collections import Counter, defaultdict
from pathlib import Path

import pdfplumber

from .ingestion import PARSERS
from .models import PipelineReport


SUPPORTED_EXTENSIONS = {".pdf"}
INTENTIONALLY_IGNORED = {
    ".csv": "structured source not enabled yet (for example Venmo)",
    ".txt": "supporting note, not a transaction source",
}


def discover(records_root, year):
    root = Path(records_root) / str(year) / "Bank Statements"
    return sorted((p for p in root.rglob("*") if p.is_file()),
                  key=lambda p: str(p).lower()) if root.exists() else []


def run_year(records_root, year, parsers=None, ignored_sources=None):
    parsers = parsers or PARSERS
    ignored_sources = ignored_sources or []
    report = PipelineReport()
    for path in discover(records_root, year):
        normalized = str(path).replace("\\", "/")
        declared = next((i for i in ignored_sources
                         if i["match"] in normalized), None)
        if declared is not None:
            report.ignored_files.append({"path": str(path),
                                         "reason": declared["reason"]})
            continue
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            # Structured sources (CSV) are offered to plugins too; only files
            # no plugin claims fall back to the explicit-ignore policy.
            if suffix == ".csv":
                try:
                    text = path.read_text(encoding="utf-8-sig", errors="replace")
                except Exception as exc:
                    report.errors.append({"path": str(path), "error": str(exc)})
                    continue
                parser = next((p for p in parsers if p.can_parse(text, str(path))), None)
                if parser is not None:
                    try:
                        account = path.parent.name
                        report.statements.append(parser.parse(str(path), account, int(year)))
                    except Exception as exc:
                        report.errors.append({"path": str(path), "error": str(exc)})
                    continue
                else:
                    report.ignored_files.append({
                        "path": str(path),
                        "reason": INTENTIONALLY_IGNORED.get(suffix, "unsupported file type"),
                    })
                    continue
            else:
                report.ignored_files.append({
                    "path": str(path),
                    "reason": INTENTIONALLY_IGNORED.get(suffix, "unsupported file type"),
                })
            continue
        try:
            with pdfplumber.open(path) as pdf:
                first = pdf.pages[0].extract_text() or "" if pdf.pages else ""
        except Exception as exc:
            report.errors.append({"path": str(path), "error": str(exc)})
            continue
        parser = next((p for p in parsers if p.can_parse(first, str(path))), None)
        if parser is None:
            report.unclaimed_files.append(str(path))
            continue
        try:
            account = path.parent.name
            report.statements.append(parser.parse(str(path), account, int(year)))
        except Exception as exc:
            report.errors.append({"path": str(path), "error": str(exc)})

    _dedupe_cross_statement(report)
    for statement in report.statements:
        statement.transactions.sort(key=lambda t: (t.date, t.source_page, t.source_line))
    return report


def _dedupe_cross_statement(report):
    """Remove only copies repeated across statements, preserving exact
    repeats within one statement. Unique transaction IDs remain untouched."""
    by_fingerprint = defaultdict(lambda: defaultdict(list))
    for statement in report.statements:
        for txn in statement.transactions:
            by_fingerprint[txn.content_fingerprint][statement.statement_id].append(txn)

    remove_ids = set()
    for _fingerprint, by_statement in by_fingerprint.items():
        if len(by_statement) < 2:
            continue
        keep_count = max(len(rows) for rows in by_statement.values())
        ordered = [t for rows in by_statement.values() for t in rows]
        for txn in ordered[keep_count:]:
            remove_ids.add(txn.transaction_id)
    if not remove_ids:
        return
    for statement in report.statements:
        before = len(statement.transactions)
        statement.transactions = [t for t in statement.transactions
                                  if t.transaction_id not in remove_ids]
        report.duplicates_removed += before - len(statement.transactions)


def transactions(report, include="all"):
    rows = report.transactions
    if include == "all":
        pass
    elif include == "expenses":
        rows = [t for t in rows if t.amount < 0]
    else:
        raise ValueError(f"unknown include policy: {include}")
    return sorted(rows, key=lambda t: (t.date, t.institution, t.account,
                                      t.source_file, t.source_page, t.source_line))
