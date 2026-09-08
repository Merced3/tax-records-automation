"""The engine: find PDFs -> route to plugins -> dedupe -> sort.

It knows nothing about any bank. It walks records/<year>/Bank Statements/,
hands each PDF to the parser plugins (first one that claims it wins),
collects Transactions, removes duplicates by fingerprint, and sorts
chronologically.

It returns a Report alongside the transactions so nothing fails silently:
every PDF is either parsed, or listed as unclaimed/errored with a reason.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime

import pdfplumber

from parsers import PLUGINS


@dataclass
class Report:
    parsed_files: int = 0
    unclaimed_files: list = field(default_factory=list)
    errored_files: list = field(default_factory=list)   # (path, error)
    duplicates_removed: int = 0


def _first_page_text(path):
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return ""
            return pdf.pages[0].extract_text() or ""
    except Exception:
        return ""


def _find_pdfs(records_root, year):
    statements_dir = os.path.join(records_root, str(year), "Bank Statements")
    if not os.path.isdir(statements_dir):
        return []
    out = []
    for dirpath, _dirs, files in os.walk(statements_dir):
        for f in sorted(files):
            if f.lower().endswith(".pdf"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def _sort_key(txn):
    try:
        return datetime.strptime(txn.date, "%m/%d/%Y")
    except ValueError:
        return datetime.max


def run_year(records_root, year):
    """Parse every statement for one year. Returns (transactions, report)."""
    report = Report()

    # Pass 1: parse every file, remember each file's transactions.
    parsed_files = []  # (pdf_path, [Transaction])
    for pdf_path in _find_pdfs(records_root, year):
        first_text = _first_page_text(pdf_path)
        plugin = next((p for p in PLUGINS if p.can_parse(first_text, pdf_path)), None)

        if plugin is None:
            report.unclaimed_files.append(pdf_path)
            continue

        # Account name = the folder the PDF sits in
        # (e.g. "Everyday Spend Bank Account").
        source_account = os.path.basename(os.path.dirname(pdf_path))

        try:
            txns = plugin.parse(pdf_path, source_account, year)
        except Exception as e:
            report.errored_files.append((pdf_path, str(e)))
            continue

        report.parsed_files += 1
        parsed_files.append((pdf_path, txns))

    # A charge is a TRUE duplicate only when two different statements re-list
    # it (overlapping periods). An identical charge listed twice WITHIN one
    # statement is real (a double-billed gym membership, say) — same
    # fingerprint, legitimately. So keep a fingerprint up to the largest
    # count any single file gives it; drop only copies beyond that.
    max_per_file = {}
    for _path, txns in parsed_files:
        counts = {}
        for t in txns:
            counts[t.fingerprint] = counts.get(t.fingerprint, 0) + 1
        for fp, n in counts.items():
            max_per_file[fp] = max(max_per_file.get(fp, 0), n)

    # Pass 2: keep each fingerprint up to its max-per-file count.
    transactions = []
    kept = {}
    for _path, txns in parsed_files:
        for t in txns:
            if kept.get(t.fingerprint, 0) >= max_per_file[t.fingerprint]:
                report.duplicates_removed += 1
                continue
            kept[t.fingerprint] = kept.get(t.fingerprint, 0) + 1
            transactions.append(t)

    transactions.sort(key=_sort_key)
    return transactions, report
