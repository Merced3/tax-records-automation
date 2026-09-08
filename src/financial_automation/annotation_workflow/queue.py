"""Pure selection/ranking for CLI, Discord, TUI, or another front-end."""

ORDERINGS = {
    "largest": lambda rows: sorted(rows, key=lambda x: abs(x[0].amount), reverse=True),
    "smallest": lambda rows: sorted(rows, key=lambda x: abs(x[0].amount)),
    "oldest": lambda rows: sorted(rows, key=lambda x: x[0].date),
    "newest": lambda rows: sorted(rows, key=lambda x: x[0].date, reverse=True),
    "merchant": lambda rows: sorted(rows, key=lambda x: x[0].merchant.lower()),
}


def need_human(transactions, states, order="largest", expenses_only=True, limit=None):
    rows = []
    for txn in transactions:
        state = states.get(txn.transaction_id)
        if state and state.human_reviewed:
            continue
        if expenses_only and txn.amount >= 0:
            continue
        rows.append((txn, state))
    if order not in ORDERINGS:
        raise ValueError(f"unknown order {order}; choices: {sorted(ORDERINGS)}")
    rows = ORDERINGS[order](rows)
    return rows if limit is None else rows[:limit]
