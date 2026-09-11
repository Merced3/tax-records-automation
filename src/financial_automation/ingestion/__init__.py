from .chase import ChaseParser
from .chase_credit import ChaseCreditParser
from .cashapp import CashAppParser

from .venmo import VenmoParser

PARSERS = [ChaseCreditParser(), ChaseParser(), CashAppParser(), VenmoParser()]
