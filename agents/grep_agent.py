"""GrepAgent — deterministic second worker, used for the portability bonus.

Uses `git log -S <term>` against bug-report keywords. No LLM, no API key, $0 cost.
Trips DIFFERENT checkpoints than ClaudeAgent — it never hallucinates SHAs or
code, but its templated rationale will trip MISSING_SYMPTOM_LINK and it tends to
trip GAVE_UP_LOW_CONFIDENCE when keywords are too generic.

PHASE 1: this is a stub. PHASE 6: real impl.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime

from agents.base import Agent, DiffSummary
from harness.materials.state import (
    BugLocation,
    FixProposal,
    InvestigationState,
    SuspectCommit,
)


def _keywords(text: str, min_len: int = 4) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", text) if len(w) >= min_len]


class GrepAgent:
    name: str = "grep"

    def __init__(self):
        pass

    def propose_candidates(self, state: InvestigationState) -> list[SuspectCommit]:
        # STUB: real impl will run git log -S <term> --since=<window>
        # for each keyword and aggregate matches.
        return []

    def locate_bug(self, state: InvestigationState, commit: SuspectCommit) -> BugLocation:
        # STUB: real impl will pick the most-modified file from the commit's diff
        # and produce a templated, low-rationale BugLocation that trips
        # MISSING_SYMPTOM_LINK by design.
        return BugLocation(
            file_path=commit.files_changed[0] if commit.files_changed else "?",
            line_range=(1, 1),
            code_snippet="",
            bug_type="introduced",
            explanation="grep: largest change in this file",
            symptom_link="",  # deliberately weak — trips MISSING_SYMPTOM_LINK
            confidence=0.3,
        )

    def compare_commits(self, sha_a: str, sha_b: str, repo_path: str) -> DiffSummary:
        return DiffSummary(sha_a=sha_a, sha_b=sha_b, summary="grep stub", key_differences=[])

    def suggest_fix(self, state: InvestigationState) -> FixProposal:
        culprit = state.confirmed_culprit()
        return FixProposal(
            file_path=culprit.files_changed[0] if culprit and culprit.files_changed else "?",
            line_range=(1, 1),
            current_code="",
            proposed_change="Consider reverting this commit.",
            rationale="grep: largest change in suspected file",
            confidence=0.2,
        )

    def reply_to_user(self, state: InvestigationState, message: str) -> str:
        return "[grep agent has no conversational mode]"
