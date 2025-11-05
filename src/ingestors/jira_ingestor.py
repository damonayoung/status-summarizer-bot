"""Jira data ingestor."""
import json
from typing import Dict, Any
from .base import BaseIngestor


class JiraIngestor(BaseIngestor):
    """Ingestor for Jira ticket data."""

    def get_source_name(self) -> str:
        return "Jira"

    def ingest(self) -> Dict[str, Any]:
        """
        Load and parse Jira data from JSON export.

        Returns:
            Structured Jira data with issues and metadata
        """
        if not self.enabled:
            return {"issues": [], "metadata": {}}

        file_path = self.config.get("path")
        if not file_path:
            raise ValueError("Jira ingestor requires 'path' in config")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data

    def format_for_prompt(self, data: Dict[str, Any]) -> str:
        """
        Format Jira data into a readable text format for the AI prompt.

        Args:
            data: Raw Jira data

        Returns:
            Formatted string representation
        """
        if not data.get("issues"):
            return "No Jira tickets available.\n"

        output = ["# JIRA TICKETS\n"]

        # Sprint metadata
        metadata = data.get("metadata", {})
        if metadata:
            output.append(f"Sprint: {metadata.get('sprint', 'N/A')}")
            output.append(f"Sprint Velocity: {metadata.get('sprintVelocity', 0)} points")
            output.append(
                f"Progress: {metadata.get('completedStoryPoints', 0)}/{metadata.get('totalStoryPoints', 0)} points\n"
            )

        # Group by status
        by_status = {}
        for issue in data["issues"]:
            status = issue["status"]
            if status not in by_status:
                by_status[status] = []
            by_status[status].append(issue)

        # Format each status group
        for status in ["In Progress", "To Do", "Done"]:
            if status not in by_status:
                continue

            output.append(f"\n## {status} ({len(by_status[status])} tickets)")
            for issue in by_status[status]:
                output.append(f"\n### [{issue['key']}] {issue['summary']}")
                output.append(f"- Priority: {issue['priority']}")
                output.append(f"- Assignee: {issue['assignee']}")
                output.append(f"- Due Date: {issue['dueDate']}")
                output.append(f"- Progress: {issue.get('progress', 0)}%")
                output.append(f"- Story Points: {issue.get('storyPoints', '?')}")

                if issue.get("description"):
                    output.append(f"- Description: {issue['description']}")

                # Include recent comments
                comments = issue.get("comments", [])
                if comments:
                    output.append("- Recent Updates:")
                    for comment in comments[-2:]:  # Last 2 comments
                        output.append(f"  - {comment['author']}: {comment['body']}")

        return "\n".join(output)
