"""The plugin contract.

The core engine knows nothing about any specific bank. It walks the records
folder, and for each PDF asks every registered plugin: "is this yours?"
The first plugin whose `can_parse` says yes gets to `parse` it.

Adding support for a new bank = adding one new file in this folder and
registering it in parsers/__init__.py. Nothing else in the system changes.
"""


class StatementParser:
    """Base class. Subclasses override both methods."""

    #: Human-readable name, used in reports.
    name = "unnamed-parser"

    def can_parse(self, first_page_text, path):
        """Return True if this PDF looks like a statement this plugin owns."""
        raise NotImplementedError

    def parse(self, path, source_account, year):
        """Extract and return a list of Transaction objects."""
        raise NotImplementedError
