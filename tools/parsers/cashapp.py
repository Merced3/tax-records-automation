"""Parser for Cash App monthly statements.

STUB — not implemented yet. The engine reports Cash App PDFs as
"unclaimed" so nothing silently goes missing. When we implement this,
we only touch this file; the rest of the system doesn't change.
"""

from parsers.base import StatementParser


class CashAppParser(StatementParser):
    name = "cashapp"

    def can_parse(self, first_page_text, path):
        return False  # not yet — never claims a file

    def parse(self, path, source_account, year):
        raise NotImplementedError("Cash App parser not implemented yet")
