"""Source interface. Every portal adapter subclasses `Source`."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..models import Listing, SearchParams

log = logging.getLogger(__name__)


class SourceError(Exception):
    """Raised when a source cannot be queried (auth, blocked, network)."""


class Source(ABC):
    name: str = "base"

    @abstractmethod
    async def search(self, params: SearchParams) -> list[Listing]:
        """Return listings roughly matching params. Over-fetching is fine:
        the pipeline applies hard filters again. Raise SourceError on failure."""


def get_sources(names: list[str]) -> list[Source]:
    """Instantiate sources by name. Unknown names are skipped with a warning."""
    from .demo import DemoSource
    from .fotocasa import FotocasaSource
    from .habitaclia import HabitacliaSource
    from .idealista import IdealistaSource
    from .pisos import PisosSource
    from .spotahome import SpotahomeSource

    registry = {
        "demo": DemoSource,
        "idealista": IdealistaSource,
        "fotocasa": FotocasaSource,
        "spotahome": SpotahomeSource,
        "habitaclia": HabitacliaSource,
        "pisos": PisosSource,
    }
    out: list[Source] = []
    for n in names:
        cls = registry.get(n)
        if cls is None:
            log.warning("Unknown source %r (known: %s)", n, ", ".join(registry))
            continue
        out.append(cls())
    return out
