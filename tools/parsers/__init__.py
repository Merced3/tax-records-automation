"""Parser plugin registry.

Order matters only for efficiency: the engine asks each plugin in turn
until one claims the PDF. New bank? Add the import and a list entry here.
"""

from parsers.chase_checking import ChaseCheckingParser
from parsers.cashapp import CashAppParser

PLUGINS = [
    ChaseCheckingParser(),
    CashAppParser(),
]
