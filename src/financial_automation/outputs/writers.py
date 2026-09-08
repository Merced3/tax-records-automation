"""Raw evidence export, tax-professional draft, final gate, and manifest."""

from pathlib import Path
import subprocess

from ..safety import atomic_write_csv, atomic_write_json, sha256_file

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


def tax_rows(transactions, states, bank_description_source="note"):
    for t in transactions:
        state = states.get(t.transaction_id)
        if bank_description_source == "note":
            description = state.note if state else ""
        elif bank_description_source == "raw":
            description = t.raw_description
        elif bank_description_source == "category_and_note":
            pieces = [] if not state else [state.category, state.note]
            description = " — ".join(p for p in pieces if p)
        else:
            raise ValueError(f"unknown bank_description_source: {bank_description_source}")
        yield [f"{t.amount:.2f}", t.date.strftime("%m/%d/%Y"), t.merchant,
               description]


def write_year(repo_root, year, transactions, states, audit_report, config,
               pipeline_report, final=False):
    root = Path(repo_root)
    raw_path = root / "output" / "raw" / f"{year}.csv"
    stage = "final" if final else "tax-professional-draft"
    tax_path = root / "output" / stage / f"{year}.csv"

    if final:
        unfinished = [t for t in transactions
                      if not states.get(t.transaction_id)
                      or not states[t.transaction_id].human_reviewed]
        if unfinished:
            raise RuntimeError(f"final export refused: {len(unfinished)} row(s) still need human review")
        if not audit_report.passed:
            raise RuntimeError("final export refused: audit failed")

    atomic_write_csv(raw_path, RAW_HEADER, raw_rows(transactions), root, "output-raw")
    source = config.get("tax_professional", {}).get("bank_description_source", "note")
    atomic_write_csv(tax_path, TAX_HEADER, tax_rows(transactions, states, source),
                     root, f"output-{stage}")

    manifest_path = root / "output" / stage / f"{year}.manifest.json"
    sources = {}
    for statement in pipeline_report.statements:
        sources[statement.path] = {
            "sha256": statement.source_sha256,
            "parser": statement.parser_name,
            "statement_id": statement.statement_id,
            "transactions": len(statement.transactions),
        }
    manifest = {
        "year": int(year), "final": final, "audit": audit_report.as_dict(),
        "transaction_count": len(transactions), "sources": sources,
        "ignored_files": pipeline_report.ignored_files,
        "raw_csv": {"path": str(raw_path), "sha256": sha256_file(raw_path)},
        "tax_csv": {"path": str(tax_path), "sha256": sha256_file(tax_path)},
        "git_commit": _git_commit(root),
    }
    atomic_write_json(manifest_path, manifest, root, f"output-{stage}")
    return raw_path, tax_path, manifest_path


def _git_commit(root):
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                       text=True).strip()
    except Exception:
        return None
