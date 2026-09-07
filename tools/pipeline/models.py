"""The one data structure everything agrees on.

A Transaction is the common currency of the pipeline: parsers produce them,
filters narrow them, writers consume them. Nobody outside this file defines
what a transaction *is*.

Every transaction carries enough provenance (source file, source account,
fingerprint) to support future auditing without re-reading any PDFs.
"""

import hashlib
from dataclasses import dataclass, field


@dataclass
class Transaction:
    amount: float          # negative = money out, positive = money in
    date: str              # MM/DD/YYYY
    merchant: str          # best-effort cleaned name (you'll refine by hand)
    description: str       # raw bank description, as printed on the statement
    source_account: str    # e.g. "Everyday Spend Bank Account"
    source_file: str       # path of the PDF this came from
    fingerprint: str = field(default="")

    def __post_init__(self):
        if not self.fingerprint:
            raw = f"{self.date}|{self.amount:.2f}|{self.description}|{self.source_account}"
            self.fingerprint = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
