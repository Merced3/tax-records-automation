"""Canonical records shared by ingestion, auditing, annotation, and output."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Dict, List, Optional


def money(value) -> Decimal:
    return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))


def digest(*parts: object, length: int = 24) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


@dataclass
class Transaction:
    institution: str
    account: str
    statement_id: str
    date: date
    amount: Decimal
    raw_description: str
    merchant: str
    source_file: str
    source_page: int
    source_line: int
    balance: Optional[Decimal] = None
    fee: Optional[Decimal] = None
    occurrence: int = 1
    provider_id: str = ""
    transaction_id: str = ""
    content_fingerprint: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        self.amount = money(self.amount)
        if self.balance is not None:
            self.balance = money(self.balance)
        if self.fee is not None:
            self.fee = money(self.fee)
        if not self.content_fingerprint:
            self.content_fingerprint = digest(
                self.institution, self.account, self.date.isoformat(),
                self.amount, self.raw_description,
            )

    def assign_id(self):
        """Assign a unique, reproducible row identity.

        When the provider supplies its own row ID (Venmo), identity comes from
        that ID so it survives file moves, renames and re-exports. Otherwise
        running balance distinguishes repeated Chase rows, and occurrence
        handles formats without a running balance (Cash App) or exact repeats.
        """
        if self.provider_id:
            self.transaction_id = digest(self.institution, self.account,
                                         "provider", self.provider_id)
            return
        self.transaction_id = digest(
            self.institution, self.account, self.statement_id,
            self.date.isoformat(), self.amount, self.raw_description,
            self.balance, self.occurrence,
        )


@dataclass
class ParsedStatement:
    path: str
    parser_name: str
    institution: str
    account: str
    statement_id: str
    period_start: date
    period_end: date
    transactions: List[Transaction]
    source_sha256: str
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class PipelineReport:
    statements: List[ParsedStatement] = field(default_factory=list)
    ignored_files: List[Dict[str, str]] = field(default_factory=list)
    unclaimed_files: List[str] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)
    duplicates_removed: int = 0

    @property
    def transactions(self):
        return [t for s in self.statements for t in s.transactions]
