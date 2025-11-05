"""Meeting notes ingestor."""
from typing import Dict, Any
from .base import BaseIngestor


class NotesIngestor(BaseIngestor):
    """Ingestor for plain text meeting notes."""

    def get_source_name(self) -> str:
        return "Meeting Notes"

    def ingest(self) -> Dict[str, Any]:
        """
        Load meeting notes from text file.

        Returns:
            Dictionary with notes content
        """
        if not self.enabled:
            return {"content": ""}

        file_path = self.config.get("path")
        if not file_path:
            raise ValueError("Notes ingestor requires 'path' in config")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        return {"content": content}

    def format_for_prompt(self, data: Dict[str, Any]) -> str:
        """
        Format meeting notes for the AI prompt.

        Args:
            data: Raw notes data

        Returns:
            Formatted string representation
        """
        content = data.get("content", "")
        if not content:
            return "No meeting notes available.\n"

        return f"# MEETING NOTES\n\n{content}\n"
