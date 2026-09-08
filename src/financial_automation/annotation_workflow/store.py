"""Durable annotation state with migration, backups, and atomic replacement."""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import hashlib
from pathlib import Path

from ..safety import atomic_write_csv, journal

MACHINE_COLUMNS = [
    "Transaction ID", "Content Fingerprint", "Institution", "Account",
    "Statement ID", "Date", "Amount", "Merchant", "Raw Bank Description",
    "Running Balance", "Fee", "Source File", "Source Page", "Source Line",
]
SUGGESTION_COLUMNS = ["Suggested Category", "Suggested Note", "Rule ID", "Rule Version"]
HUMAN_COLUMNS = ["Category", "Tax Treatment", "Note"]
STATE_COLUMNS = ["Review Status", "Updated At"]
HEADER = MACHINE_COLUMNS + SUGGESTION_COLUMNS + HUMAN_COLUMNS + STATE_COLUMNS


@dataclass
class AnnotationState:
    category: str = ""
    tax_treatment: str = ""
    note: str = ""
    suggested_category: str = ""
    suggested_note: str = ""
    rule_id: str = ""
    rule_version: str = ""
    updated_at: str = ""

    @property
    def human_reviewed(self):
        return bool(self.category.strip() or self.tax_treatment.strip() or self.note.strip())

    @property
    def has_suggestion(self):
        return bool(self.suggested_category.strip() or self.suggested_note.strip())

    @property
    def status(self):
        return "human-reviewed" if self.human_reviewed else ("suggested" if self.has_suggestion else "needs-review")


def _legacy_fingerprint(txn):
    raw = f"{txn.date:%m/%d/%Y}|{txn.amount:.2f}|{txn.raw_description}|{txn.account}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _read(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_states(path):
    """Return transaction-id -> state for the current schema."""
    states = {}
    for row in _read(path):
        transaction_id = (row.get("Transaction ID") or "").strip()
        if transaction_id:
            states[transaction_id] = _state(row)
    return states


def _state(row):
    return AnnotationState(
        category=row.get("Category", ""),
        tax_treatment=row.get("Tax Treatment", ""),
        note=row.get("Note", ""),
        suggested_category=row.get("Suggested Category", ""),
        suggested_note=row.get("Suggested Note", ""),
        rule_id=row.get("Rule ID", ""), rule_version=row.get("Rule Version", ""),
        updated_at=row.get("Updated At", ""),
    )


def _human_values(row):
    return {key: row.get(key, "") for key in HUMAN_COLUMNS}


def generate(transactions, path, rules, repo_root):
    """Migrate/refresh annotation state without losing human text.

    Legacy rows match via the old fingerprint, including duplicates via a
    queue. New rows match by unique Transaction ID. Suggestions are always
    recomputed into separate columns and can never overwrite Category/Note.
    Any unmatched human row aborts the rewrite rather than silently dropping
    work. The old file is backed up, then replacement is atomic.
    """
    old_rows = _read(path)
    by_id = {r.get("Transaction ID", ""): r for r in old_rows if r.get("Transaction ID")}

    # Compare against the last machine-written baseline. This detects edits
    # made externally in Excel/VS Code and records an append-only row history.
    baseline_path = (Path(repo_root) / "backups" / "state" / "annotations" /
                     Path(path).name)
    baseline_rows = _read(baseline_path)
    baseline_by_id = {r.get("Transaction ID", ""): r for r in baseline_rows
                      if r.get("Transaction ID")}
    changed_ids = set()
    changes = []
    for transaction_id, row in by_id.items():
        prior = baseline_by_id.get(transaction_id)
        if prior is not None and _human_values(row) != _human_values(prior):
            changed_ids.add(transaction_id)
            changes.append({"transaction_id": transaction_id,
                            "old": _human_values(prior), "new": _human_values(row)})
    if changes:
        journal(repo_root, "annotation-human-changes", {"path": str(path),
                                                        "changes": changes})

    legacy = defaultdict(deque)
    legacy_by_fields = defaultdict(deque)
    for row in old_rows:
        if not row.get("Transaction ID"):
            legacy[row.get("Fingerprint", "")].append(row)
            legacy_by_fields[(row.get("Date", ""), row.get("Amount", ""),
                              row.get("Bank Description", ""))].append(row)

    output = []
    matched_old = set()
    human = suggested = needs = migrated = restored_deleted = 0
    now = datetime.now(timezone.utc).isoformat()
    from .rules import suggest

    for txn in transactions:
        old = by_id.get(txn.transaction_id)
        if old is not None:
            matched_old.add(id(old))
        elif txn.transaction_id in baseline_by_id:
            # The transaction row was deleted from the editable CSV. Restore
            # its last machine-known annotation state from the private
            # baseline instead of recreating it blank.
            old = baseline_by_id[txn.transaction_id]
            restored_deleted += 1
        elif legacy[_legacy_fingerprint(txn)]:
            old = legacy[_legacy_fingerprint(txn)].popleft()
            matched_old.add(id(old)); migrated += 1
        else:
            # Older parser versions occasionally changed only description
            # joining/fingerprint text. Exact date+amount+raw description is
            # a safe migration fallback; it also disambiguates equal-amount
            # transfers from merchant purchases.
            key = (txn.date.strftime("%m/%d/%Y"), f"{txn.amount:.2f}",
                   txn.raw_description)
            candidates = legacy_by_fields[key]
            while candidates and id(candidates[0]) in matched_old:
                candidates.popleft()
            if candidates:
                old = candidates.popleft()
                matched_old.add(id(old)); migrated += 1
            else:
                old = {}
        state = _state(old)
        proposal = suggest(txn, rules)
        state.suggested_category = proposal.category
        state.suggested_note = proposal.note
        state.rule_id = proposal.rule_id
        state.rule_version = proposal.rule_version
        if state.human_reviewed:
            human += 1
        elif proposal.present:
            suggested += 1
        else:
            needs += 1
        if txn.transaction_id in changed_ids or (old and state.human_reviewed and not state.updated_at):
            state.updated_at = now
        output.append(_row(txn, state))

    unmatched_human = []
    for row in old_rows:
        if id(row) not in matched_old and _state(row).human_reviewed:
            unmatched_human.append(row)
    if unmatched_human:
        raise RuntimeError(
            f"SAFETY STOP: {len(unmatched_human)} human-annotated row(s) no longer "
            "match transactions. Nothing was rewritten; the current file remains intact."
        )

    rows_for_csv = [[r[c] for c in HEADER] for r in output]
    atomic_write_csv(path, HEADER, rows_for_csv, repo_root, "annotations")
    # Private baseline for detecting future external row edits. It is itself
    # written atomically but does not recursively create backups.
    atomic_write_csv(baseline_path, HEADER, rows_for_csv)
    journal(repo_root, "annotations-generated", {
        "path": str(path), "rows": len(output), "human": human,
        "suggested": suggested, "needs_review": needs, "legacy_migrated": migrated,
        "deleted_rows_restored": restored_deleted,
    })
    return {"rows": len(output), "human": human, "suggested": suggested,
            "needs_review": needs, "legacy_migrated": migrated,
            "deleted_rows_restored": restored_deleted}


def _row(txn, state):
    return {
        "Transaction ID": txn.transaction_id,
        "Content Fingerprint": txn.content_fingerprint,
        "Institution": txn.institution, "Account": txn.account,
        "Statement ID": txn.statement_id, "Date": txn.date.strftime("%m/%d/%Y"),
        "Amount": f"{txn.amount:.2f}", "Merchant": txn.merchant,
        "Raw Bank Description": txn.raw_description,
        "Running Balance": "" if txn.balance is None else f"{txn.balance:.2f}",
        "Fee": "" if txn.fee is None else f"{txn.fee:.2f}",
        "Source File": txn.source_file, "Source Page": txn.source_page,
        "Source Line": txn.source_line,
        "Suggested Category": state.suggested_category,
        "Suggested Note": state.suggested_note, "Rule ID": state.rule_id,
        "Rule Version": state.rule_version, "Category": state.category,
        "Tax Treatment": state.tax_treatment, "Note": state.note,
        "Review Status": state.status, "Updated At": state.updated_at,
    }
