"""Support module for cross-file feature-tour analysis."""

from __future__ import annotations


def format_summary(workspace_name: str, status: str) -> str:
    return f"{workspace_name}:{status}"


def helper_label(kind: str) -> str:
    return f"label:{kind}"
