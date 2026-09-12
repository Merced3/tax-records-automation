"""Raw evidence export, tax-professional draft, final gate, and manifest.

Two views of the same accepted transactions coexist:

- Statement view: rows grouped as their source statements organise them. This
  is the unit of arithmetic reconciliation and is never rearranged.
- Calendar-year view: the same rows regrouped by actual transaction date, which
  is what a tax year means. A January statement legitimately supplies prior
  December activity.

Deriving the second from the first does not weaken the first; source evidence
and annotation grouping are untouched.
"""

from decimal import Decimal
from pathlib import Path

from ..safety import atomic_write_csv, atomic_write_json, sha256_file
from .provenance import decision_provenance, git_state, input_hashes

RAW_HEADER = [
    "Transaction ID", "Content Fingerprint", "Institution", "Account",
    "Statement ID", "Date", "Amount", "Merchant", "Raw Bank Description",
    "Running Balance", "Fee", "Source File", "Source Page", "Source Line",
]
TAX_HEADER = ["Amount", "Date", "Merchant", "Bank Description"]


def raw_rows(transactions):
    for t in transactions:
        yield [
            t.transaction_id, t.content_fingerprint, t.institution, t.account,
            t.statement_id, t.date.strftime("%m/%d/%Y"), f"{t.amount:.2f}",
            t.merchant, t.raw_description,
            "" if t.balance is None else f"{t.balance:.2f}",
            "" if t.fee is None else f"{t.fee:.2f}", t.source_file,
            t.source_page, t.source_line,
        ]


def tax_rows(transactions, states, bank_description_source="note", resolved=None):
    """Professional draft rows.

    Values come from field-level resolution when available (human overrides
    first, then owner-approved rules), never from unapproved suggestions.
    """
    for t in transactions:
        state = states.get(t.transaction_id)
        result = (resolved or {}).get(t.transaction_id)
        category = result.category if result else (state.category if state else "")
        note = result.note if result else (state.note if state else "")
        if bank_description_source == "note":
            description = note
        elif bank_description_source == "raw":
            description = t.raw_description
        elif bank_description_source == "category_and_note":
            description = " — ".join(p for p in (category, note) if p)
        else:
            raise ValueError(f"unknown bank_description_source: {bank_description_source}")
        yield [f"{t.amount:.2f}", t.date.strftime("%m/%d/%Y"), t.merchant,
               description]


def write_year(repo_root, year, transactions, states, audit_report, config,
               pipeline_report, final=False, resolved=None, coverage_report=None,
               approvals=None):
    root = Path(repo_root)
    raw_path = root / "output" / "raw" / f"{year}.csv"
    stage = "final" if final else "tax-professional-draft"
    tax_path = root / "output" / stage / f"{year}.csv"

    if final:
        if resolved is None:
            raise RuntimeError("final export requires field-level resolution")
        unfinished = [t for t in transactions
                      if not (resolved.get(t.transaction_id)
                              and resolved[t.transaction_id].deliverable)]
        if unfinished:
            raise RuntimeError(
                f"final export refused: {len(unfinished)} row(s) lack a resolved "
                "Category and Note (human override or owner-approved rule)")
        if not audit_report.passed:
            raise RuntimeError("final export refused: audit failed")
        if coverage_report is not None and not coverage_report.complete:
            raise RuntimeError(
                "final export refused: statement coverage for this year is "
                "incomplete or has declared missing history; run "
                f"`coverage {year}` and resolve or acknowledge it")

    atomic_write_csv(raw_path, RAW_HEADER, raw_rows(transactions), root, "output-raw")
    source = config.get("tax_professional", {}).get("bank_description_source", "note")
    atomic_write_csv(tax_path, TAX_HEADER,
                     tax_rows(transactions, states, source, resolved),
                     root, f"output-{stage}")

    manifest_path = root / "output" / stage / f"{year}.manifest.json"
    sources = {}
    for statement in pipeline_report.statements:
        sources[statement.path] = {
            "sha256": statement.source_sha256,
            "parser": statement.parser_name,
            "statement_id": statement.statement_id,
            "period_start": statement.period_start.isoformat(),
            "period_end": statement.period_end.isoformat(),
            "period_source": statement.period_source,
            "transactions": len(statement.transactions),
        }

    in_year, out_of_year = calendar_year_split(transactions, year)
    git = git_state(root)
    manifest = {
        "year": int(year), "final": final, "audit": audit_report.as_dict(),
        "transaction_count": len(transactions), "sources": sources,
        "ignored_files": pipeline_report.ignored_files,
        "raw_csv": {"path": str(raw_path), "sha256": sha256_file(raw_path)},
        "tax_csv": {"path": str(tax_path), "sha256": sha256_file(tax_path)},
        "calendar_year": {
            "rows_dated_in_year": len(in_year),
            "rows_dated_outside_year": len(out_of_year),
            "note": "statement folders can contain rows dated in an adjacent "
                    "year; the calendar-year export regroups by transaction date",
        },
        "inputs": input_hashes(root, config, year),
        "git": git,
        # Kept for compatibility with earlier manifests.
        "git_commit": git.get("commit"),
    }
    if resolved is not None:
        manifest["decision_sources"] = decision_provenance(resolved)
        manifest["deliverable_rows"] = sum(1 for r in resolved.values() if r.deliverable)
    if approvals is not None:
        manifest["rule_approvals"] = [
            {"rule_id": a.rule_id, "version": a.version, "years": a.years,
             "approved_at": a.approved_at, "approved_by": a.approved_by}
            for a in approvals]
    if coverage_report is not None:
        manifest["coverage"] = {
            "complete": coverage_report.complete,
            "undeclared_gap_days": coverage_report.undeclared_gap_days,
            "known_missing": coverage_report.known_gaps,
            "accounts": [
                {"institution": a.institution, "account": a.account,
                 "statements": a.statements, "covered_days": a.covered_days,
                 "year_days": a.year_days,
                 "period_unmeasurable": a.period_unmeasurable,
                 "gaps": [[s.isoformat(), e.isoformat()] for s, e in a.gaps]}
                for a in coverage_report.accounts],
        }
    atomic_write_json(manifest_path, manifest, root, f"output-{stage}")
    return raw_path, tax_path, manifest_path


def calendar_year_split(transactions, year):
    """Partition rows by whether their transaction date falls in `year`."""
    year = int(year)
    in_year = [t for t in transactions if t.date.year == year]
    outside = [t for t in transactions if t.date.year != year]
    return in_year, outside


def write_calendar_year(repo_root, year, statement_years, states, config,
                        resolved=None, final=False):
    """Write the calendar-year view assembled from several statement years.

    `statement_years` maps a statement-folder year to its accepted rows. Rows
    are selected purely by transaction date, so December activity that arrives
    on a January statement lands in the correct tax year. Every row keeps its
    Transaction ID and source location, so the derived view remains traceable
    back to the statement that proved it.
    """
    root = Path(repo_root)
    year = int(year)
    selected = []
    contributions = {}
    for folder_year, rows in sorted(statement_years.items()):
        matched = [t for t in rows if t.date.year == year]
        if matched:
            contributions[int(folder_year)] = len(matched)
        selected.extend(matched)
    selected.sort(key=lambda t: (t.date, t.institution, t.account,
                                 t.source_file, t.source_page, t.source_line))

    seen = set()
    for t in selected:
        if t.transaction_id in seen:
            raise RuntimeError(
                "calendar-year export refused: duplicate Transaction ID "
                f"{t.transaction_id} appears in more than one statement year")
        seen.add(t.transaction_id)

    path = root / "output" / ("calendar-year-final" if final else "calendar-year") / f"{year}.csv"
    source = config.get("tax_professional", {}).get("bank_description_source", "note")
    atomic_write_csv(path, TAX_HEADER,
                     tax_rows(selected, states, source, resolved),
                     root, "output-calendar-year")

    raw_path = root / "output" / "calendar-year-raw" / f"{year}.csv"
    atomic_write_csv(raw_path, RAW_HEADER, raw_rows(selected), root,
                     "output-calendar-year-raw")

    manifest = {
        "calendar_year": year,
        "rows": len(selected),
        "contributing_statement_years": contributions,
        "amount_total": str(sum((t.amount for t in selected), Decimal("0.00"))),
        "derivation": "rows selected by transaction date from audited statement "
                      "years; source statements and annotations unchanged",
        "inputs": input_hashes(root, config, year),
        "git": git_state(root),
        "csv": {"path": str(path), "sha256": sha256_file(path)},
        "raw_csv": {"path": str(raw_path), "sha256": sha256_file(raw_path)},
    }
    if resolved is not None:
        deliverable = [t for t in selected
                       if resolved.get(t.transaction_id)
                       and resolved[t.transaction_id].deliverable]
        manifest["deliverable_rows"] = len(deliverable)
        manifest["decision_sources"] = decision_provenance(
            {t.transaction_id: resolved[t.transaction_id] for t in selected
             if t.transaction_id in resolved})
    manifest_path = path.with_suffix(".manifest.json")
    atomic_write_json(manifest_path, manifest, root, "output-calendar-year")
    return path, raw_path, manifest_path
