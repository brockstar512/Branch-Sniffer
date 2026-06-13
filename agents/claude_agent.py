"""ClaudeAgent — primary LLM-backed worker.

PHASE 1: stub returning canned data so the loop runs end-to-end.
PHASE 2: real Anthropic SDK integration with structured output.

The real implementation will:
  - propose_candidates: read git log metadata, ask Claude to filter to suspects
  - locate_bug: pull `git show <sha>` diff, ask Claude to identify file:line:type
  - compare_commits: pull `git diff a b`, ask Claude to summarize
  - suggest_fix: based on located bug, ask Claude to propose a change
  - reply_to_user: handle conversational turns
"""
from __future__ import annotations

from datetime import datetime

from agents.base import Agent, DiffSummary
from harness.materials.state import (
    BugLocation,
    FixProposal,
    InvestigationState,
    SuspectCommit,
)


class ClaudeAgent:
    name: str = "claude"

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-5"):
        self.api_key = api_key
        self.model = model
        # TODO: from anthropic import Anthropic; self.client = Anthropic(api_key=api_key)

    def propose_candidates(self, state: InvestigationState) -> list[SuspectCommit]:
        # STUB: returns a single fake suspect
        # Real impl: git log --since=<window> --pretty=... --name-only,
        # filter by FILE_EXTENSION_SCOPE and keywords, ask Claude to rank.
        return [
            SuspectCommit(
                sha="0000000000000000000000000000000000000000",
                short_sha="0000000",
                author="stub",
                date=datetime.utcnow(),
                message="[stub] placeholder candidate",
                files_changed=["stub.cs"],
                confidence=0.5,
                rationale="stub: replace with real candidate proposal",
            )
        ]

    def locate_bug(self, state: InvestigationState, commit: SuspectCommit) -> BugLocation:
        # STUB
        return BugLocation(
            file_path=commit.files_changed[0] if commit.files_changed else "stub.cs",
            line_range=(1, 1),
            code_snippet="// stub",
            bug_type="introduced",
            explanation="stub: replace with real diff analysis",
            symptom_link="stub: replace with real causal explanation linking code to symptom",
            confidence=0.5,
        )

    def compare_commits(self, sha_a: str, sha_b: str, repo_path: str) -> DiffSummary:
        return DiffSummary(
            sha_a=sha_a,
            sha_b=sha_b,
            summary="stub comparison",
            key_differences=["stub"],
        )

    def suggest_fix(self, state: InvestigationState) -> FixProposal:
        culprit = state.confirmed_culprit()
        return FixProposal(
            file_path=culprit.files_changed[0] if culprit and culprit.files_changed else "stub.cs",
            line_range=(1, 1),
            current_code="// stub",
            proposed_change="// stub fix",
            rationale="stub: replace with real fix proposal",
            confidence=0.5,
        )

    def reply_to_user(self, state: InvestigationState, message: str) -> str:
        return "[stub] reply"
