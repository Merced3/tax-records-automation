"""Pure selection/ranking for CLI, Discord, TUI, or another front-end."""

from .resolution import resolve

ORDERINGS = {
    "largest": lambda rows: sorted(rows, key=lambda x: abs(x[0].amount), reverse=True),
    "smallest": lambda rows: sorted(rows, key=lambda x: abs(x[0].amount)),
    "oldest": lambda rows: sorted(rows, key=lambda x: x[0].date),
    "newest": lambda rows: sorted(rows, key=lambda x: x[0].date, reverse=True),
    "merchant": lambda rows: sorted(rows, key=lambda x: x[0].merchant.lower()),
}


def need_human(transactions, states, order="largest", expenses_only=True,
               limit=None, approvals=None):
    """Rows that still lack a resolved Category AND Note.

    With `approvals`, a row covered by an owner-approved rule is complete and
    does not appear: the owner decided once, for the rule. Without approvals
    the older behaviour applies (any human-typed field counts as reviewed).
    """
    rows = []
    for txn in transactions:
        state = states.get(txn.transaction_id)
        if approvals is None:
            if state and state.human_reviewed:
                continue
        else:
            if resolve(txn, state, approvals).deliverable:
                continue
        if expenses_only and txn.amount >= 0:
            continue
        rows.append((txn, state))
    if order not in ORDERINGS:
        raise ValueError(f"unknown order {order}; choices: {sorted(ORDERINGS)}")
    rows = ORDERINGS[order](rows)
    return rows if limit is None else rows[:limit]


def rule_approval_queue(transactions, states, approvals):
    """Rules whose suggestions are blocking rows, ranked by how many rows each
    would resolve. This is the efficient unit of owner review: approving one
    recurring rule can settle hundreds of rows without retyping them."""
    from .resolution import STALE, UNAPPROVED
    pending = {}
    for txn in transactions:
        state = states.get(txn.transaction_id)
        result = resolve(txn, state, approvals)
        if result.deliverable or not result.rule_id:
            continue
        blocked = {result.category_source, result.note_source} & {UNAPPROVED, STALE}
        if not blocked:
            continue
        key = (result.rule_id, result.rule_version)
        entry = pending.setdefault(key, {"rows": 0, "state": sorted(blocked)[0],
                                         "example": txn,
                                         "category": state.suggested_category,
                                         "note": state.suggested_note})
        entry["rows"] += 1
    return sorted(pending.items(), key=lambda kv: -kv[1]["rows"])
