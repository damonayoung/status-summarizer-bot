"""Base class for data ingestors."""
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseIngestor(ABC):
    """Abstract base class for all data ingestors."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get("enabled", True)

    @abstractmethod
    def ingest(self) -> Dict[str, Any]:
        """
        Ingest data from the source.

        Returns:
            Dict containing structured data from the source
        """
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Return the name of this data source."""
        pass
