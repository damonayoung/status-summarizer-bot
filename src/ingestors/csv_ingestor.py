"""Generic CSV ingestor for tabular data sources."""
import csv
from typing import Dict, Any, List
from .base import BaseIngestor


class CSVIngestor(BaseIngestor):
    """Generic CSV ingestor that reads CSV files and formats them for AI prompts."""

    def __init__(self, config: Dict[str, Any], source_name: str = "CSV"):
        super().__init__(config)
        self.source_name = source_name
        self.path = config.get("path")

    def ingest(self) -> Dict[str, Any]:
        """
        Ingest data from CSV file.

        Returns:
            Dict containing:
                - headers: List of column names
                - rows: List of dicts (each row as a dict)
                - row_count: Number of rows
        """
        if not self.path:
            raise ValueError(f"{self.source_name}: No path specified in config")

        headers = []
        rows = []

        with open(self.path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = list(reader)

        return {
            "headers": headers,
            "rows": rows,
            "row_count": len(rows)
        }

    def get_source_name(self) -> str:
        """Return the name of this data source."""
        return self.source_name

    def format_for_prompt(self, data: Dict[str, Any]) -> str:
        """
        Format CSV data for AI prompt.

        Args:
            data: Dict with headers and rows

        Returns:
            Formatted text representation
        """
        headers = data.get("headers", [])
        rows = data.get("rows", [])

        if not rows:
            return f"# {self.source_name.upper()}\n(No data available)"

        # Format as structured text
        lines = [f"# {self.source_name.upper()}"]
        lines.append(f"Total Records: {len(rows)}")
        lines.append("")

        # Create a simple text table format
        for idx, row in enumerate(rows, 1):
            lines.append(f"## Record {idx}")
            for key, value in row.items():
                if value:  # Only include non-empty values
                    lines.append(f"  - {key}: {value}")
            lines.append("")

        return "\n".join(lines)
