"""Which transactions make it into the output.

Selected by the `include` key in config.yaml. New policies go here —
the engine just calls `apply(transactions, config["include"])`.
"""


def include_all(transactions):
    return transactions


def expenses_only(transactions):
    return [t for t in transactions if t.amount < 0]


POLICIES = {
    "all": include_all,
    "expenses": expenses_only,
}


def apply(transactions, policy_name):
    if policy_name not in POLICIES:
        raise ValueError(
            f"Unknown include policy {policy_name!r}. "
            f"Choices: {sorted(POLICIES)}"
        )
    return POLICIES[policy_name](transactions)
