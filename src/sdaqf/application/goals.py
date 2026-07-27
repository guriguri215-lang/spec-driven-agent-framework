"""Deterministic Codex goal-template rendering."""

from __future__ import annotations

import re


class GoalTemplateService:
    """Render the minimum complete Goal execution contract."""

    _SECTIONS = (
        "Objective",
        "Context",
        "Constraints",
        "Done when",
        "Checkpoints",
        "Stop conditions",
        "Approval gates",
        "Sandbox handling",
        "Language policy",
    )

    def render(self, milestone_id: str) -> str:
        """Render an English prompt with all required sections."""

        normalized = milestone_id.strip()
        if not normalized:
            raise ValueError("milestone_id must not be empty")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", normalized):
            raise ValueError("milestone_id must be a safe ASCII identifier")
        values = {
            "Objective": f"Complete {normalized} with verifiable evidence.",
            "Context": "Read the approved specification, active plan, and current handoff.",
            "Constraints": (
                "Stay within the milestone scope and preserve Git and privacy boundaries."
            ),
            "Done when": "All required acceptance criteria pass and the local worktree is clean.",
            "Checkpoints": (
                "Record implementation, validation, independent review, and final Git state."
            ),
            "Stop conditions": (
                "Stop for unsafe overwrite, secrets, unresolved Must conflicts, or "
                "unavailable mandatory commands."
            ),
            "Approval gates": (
                "Ask the Owner before publication, destructive changes, license selection, "
                "credentials, or external effects."
            ),
            "Sandbox handling": (
                "Classify denial separately from absence and request only one minimal "
                "technical approval for an already authorized command."
            ),
            "Language policy": "Use English for every GitHub-facing artifact and metadata item.",
        }
        body = [f"# Goal: {normalized}", ""]
        for section in self._SECTIONS:
            body.extend((f"## {section}", "", values[section], ""))
        return "\n".join(body).rstrip() + "\n"
