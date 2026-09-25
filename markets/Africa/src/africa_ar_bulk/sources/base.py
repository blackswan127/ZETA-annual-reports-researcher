from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import Candidate, Issuer


class BaseSourceAdapter(ABC):
    @abstractmethod
    async def discover_candidates(
        self,
        issuer: Issuer,
        start_year: int,
        end_year: int,
    ) -> List[Candidate]:
        """Discover annual report candidates for an issuer across fiscal years."""
        pass
