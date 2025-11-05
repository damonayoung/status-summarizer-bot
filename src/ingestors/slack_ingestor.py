"""Slack threads data ingestor."""
import json
from typing import Dict, Any
from .base import BaseIngestor


class SlackIngestor(BaseIngestor):
    """Ingestor for Slack conversation threads."""

    def get_source_name(self) -> str:
        return "Slack"

    def ingest(self) -> Dict[str, Any]:
        """
        Load and parse Slack thread data from JSON export.

        Returns:
            Structured Slack data with channels and threads
        """
        if not self.enabled:
            return {"channels": [], "metadata": {}}

        file_path = self.config.get("path")
        if not file_path:
            raise ValueError("Slack ingestor requires 'path' in config")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data

    def format_for_prompt(self, data: Dict[str, Any]) -> str:
        """
        Format Slack data into a readable text format for the AI prompt.

        Args:
            data: Raw Slack data

        Returns:
            Formatted string representation
        """
        if not data.get("channels"):
            return "No Slack conversations available.\n"

        output = ["# SLACK CONVERSATIONS\n"]

        for channel in data["channels"]:
            channel_name = channel["channel_name"]
            threads = channel.get("threads", [])

            if not threads:
                continue

            output.append(f"\n## {channel_name} ({len(threads)} discussions)\n")

            for thread in threads:
                # Main message
                author = thread["author"]
                text = thread["text"]
                timestamp = thread["thread_ts"]

                output.append(f"### @{author} - {timestamp}")
                output.append(f"{text}\n")

                # Reactions
                reactions = thread.get("reactions", [])
                if reactions:
                    reaction_str = ", ".join(
                        [f":{r['emoji']}: {r['count']}" for r in reactions]
                    )
                    output.append(f"Reactions: {reaction_str}\n")

                # Replies
                replies = thread.get("replies", [])
                if replies:
                    output.append("Thread replies:")
                    for reply in replies:
                        output.append(f"  → {reply['author']}: {reply['text']}")
                    output.append("")  # Blank line

        return "\n".join(output)
