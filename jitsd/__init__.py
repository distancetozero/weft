"""JIT-SD reference implementation -- rung 1 (solo, offline, no contracts).

See docs/07-adoption.md for the rung ladder. This package deliberately
implements only what one person alone needs, because nothing above rung 1 may
be required for rung 1 to be useful.
"""

__version__ = "0.1.0"

from .store import ObjectStore, Stats          # noqa: F401
from .ledger import Ledger, Repo, Revision, Baseline  # noqa: F401
