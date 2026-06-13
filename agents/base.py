"""Agent Protocol — the swappable interface.

The harness only imports this Protocol. Concrete agents (ClaudeAgent,
GrepAgent) live in this package but the loop never references them directly.
To swap agents, change the construction in the CLI/Streamlit entry point.
"""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from harness.materials.state import (
    BugLocation,
    FixProposal,
    InvestigationState,
    SuspectCommit,
)


class DiffSummary(BaseModel):
    sha_a: str
    sha_b: str
    summary: str
    key_differences: list[str] = []


class Agent(Protocol):
    name: str

    def propose_candidates(self, state: InvestigationState) -> list[SuspectCommit]: ...

    def locate_bug(self, state: InvestigationState, commit: SuspectCommit) -> BugLocation: ...

    def compare_commits(self, sha_a: str, sha_b: str, repo_path: str) -> DiffSummary: ...

    def suggest_fix(self, state: InvestigationState) -> FixProposal: ...

    def reply_to_user(self, state: InvestigationState, message: str) -> str: ...
