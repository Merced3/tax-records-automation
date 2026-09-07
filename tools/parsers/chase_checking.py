"""Parser for Chase checking/savings statements (JPMorgan Chase Bank).

Chase statements have a real text layer (no OCR needed). Transaction lines
inside the TRANSACTION DETAIL section look like:

    03/09 Card Purchase 03/07 Circle K #2741088 San Antonio TX Card 5265 -48.88 662.18

Pattern: MM/DD <free-text description> <amount> <running balance>
Long descriptions can wrap onto continuation lines, which we re-join.
"""

import re

import pdfplumber

from parsers.base import StatementParser
from pipeline.models import Transaction

# A transaction line: date, description, amount, running balance.
TXN_RE = re.compile(
    r"^(\d{2}/\d{2})\s+(.+?)\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})\s*$"
)

# Lines that look like transactions but are actually section furniture.
SKIP_PREFIXES = ("Beginning Balance", "Ending Balance")

# Noise we strip out of descriptions to guess a merchant name.
# Best-effort only — the raw description column always keeps the full text.
_MERCHANT_PATTERNS = [
    r"^(Recurring )?Card Purchase( With Pin)? \d{2}/\d{2} ",   # card prefix
    r"^Payment Received \d{2}/\d{2} ",                           # deposit prefix
    r"^\d{2}/\d{2} ",                                            # leading stray date
    r"\s+Card \d+$",                                             # trailing card number
    r"\s+(Web|CCD) ID:.*$",                                      # ACH trace IDs
]


def _clean_merchant(desc):
    s = desc
    for pat in _MERCHANT_PATTERNS:
        s = re.sub(pat, "", s)
    return s.strip(" -")


class ChaseCheckingParser(StatementParser):
    name = "chase-checking"

    def can_parse(self, first_page_text, path):
        return "JPMorgan Chase Bank" in first_page_text

    def parse(self, path, source_account, year):
        transactions = []
        with pdfplumber.open(path) as pdf:
            in_detail = False
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.splitlines():
                    line = line.strip()
                    if "*start*transaction detail" in line:
                        in_detail = True
                        continue
                    if "*end*transaction detail" in line:
                        in_detail = False
                        continue
                    if not in_detail:
                        continue
                    if line.startswith(SKIP_PREFIXES):
                        continue

                    m = TXN_RE.match(line)
                    if m:
                        date_mmdd, desc, amount_s, _balance = m.groups()
                        transactions.append(self._make_txn(
                            date_mmdd, desc, amount_s, source_account, path, year
                        ))
                    elif transactions and line and not line.startswith(("DATE", "Page")):
                        # Wrapped description continuation — re-join it.
                        prev = transactions[-1]
                        prev.description += " " + line
        return transactions

    def _make_txn(self, date_mmdd, desc, amount_s, account, path, year):
        amount = float(amount_s.replace(",", ""))
        date = f"{date_mmdd}/{year}"
        merchant = _clean_merchant(desc) or desc
        return Transaction(
            amount=amount,
            date=date,
            merchant=merchant,
            description=desc,
            source_account=account,
            source_file=str(path),
        )
