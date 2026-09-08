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

# Chase's text layer FUSES page furniture into transaction lines at page
# breaks. The end-of-section marker and the "Page X of Y" footer can share a
# baseline with the page's last transaction, producing e.g.:
#   "*end*transac1tion detail0/31 Zelle Payment To Renimol ... -1,295.00 168.53"
# If we only matched clean lines we'd silently drop that transaction. So we
# strip the fused noise and re-match. The marker itself is corrupted by the
# fusion ("transac1tion", "detail0/31"), so we match it loosely.
_END_MARKER_FUSED = re.compile(r"\*end\*transac\w*\s*detail", re.IGNORECASE)
_PAGE_FOOTER = re.compile(r"^Page\s+of\s*$|^\d+\s+\d+$")

# When the end-marker fuses with a transaction, the date's leading digit gets
# absorbed: real "10/31" appears as "transac1tion detail0/31" — the "1" went
# into "transac1tion" and "detail" swallowed the rest. We recover it as
# "1" + the digits that follow "detail".
_FUSED_DATE = re.compile(r"detail(\d/\d{2})")

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
                for raw in text.splitlines():
                    line = raw.strip()
                    squashed = line.replace(" ", "")

                    # Chase is inconsistent: older statements use
                    # "*start*transaction detail" (spaces), newer ones use
                    # "*start*transactiondetail" (none). Normalize.
                    if "*start*transactiondetail" in squashed:
                        in_detail = True
                        continue

                    # An end-marker may be FUSED to a trailing transaction
                    # (see _FUSED_DATE note). Detect it loosely because fusion
                    # corrupts the marker text itself.
                    if "*end*transac" in squashed:
                        txn = self._recover_fused(line, source_account, path, year)
                        if in_detail and txn is not None:
                            transactions.append(txn)
                        in_detail = False
                        continue

                    if not in_detail:
                        continue
                    if line.startswith(SKIP_PREFIXES) or _PAGE_FOOTER.match(line):
                        continue

                    m = TXN_RE.match(line)
                    if m:
                        date_mmdd, desc, amount_s, _balance = m.groups()
                        transactions.append(self._make_txn(
                            date_mmdd, desc, amount_s, source_account, path, year
                        ))
                    elif (transactions and line
                          and not line.startswith("DATE")
                          and "transactiondetail" not in line.replace(" ", "").lower()
                          and not line.startswith(("(continued)", "TRANSACTION", "Account Number"))):
                        # Wrapped description continuation — re-join it. But
                        # never re-join section headers/footers that bleed in.
                        transactions[-1].description += " " + line
        return transactions

    def _recover_fused(self, line, account, path, year):
        """Pull a transaction out of a line fused with the end-marker.

        Returns a Transaction, or None if the line is just the marker with no
        transaction glued on. The date's leading digit is absorbed into the
        corrupted marker ("transac1tion detail0/31" = date 10/31); we rebuild
        it as "1" + whatever digit follows "detail".
        """
        dm = _FUSED_DATE.search(line)
        if not dm:
            return None
        date_mmdd = "1" + dm.group(1)
        # Strip everything up through "detail<date>" to isolate the
        # description + amount + balance.
        tail = line[dm.end():].strip()
        m = re.match(r"^(.+?)\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})\s*$", tail)
        if not m:
            return None
        desc, amount_s, _balance = m.groups()
        return self._make_txn(date_mmdd, desc, amount_s, account, path, year)

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
