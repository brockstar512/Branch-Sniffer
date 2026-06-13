"""Investigation state models — the single source of truth flowing through the loop.

Pillar 3 (Materials) lives here. Every other pillar reads from and writes to
`InvestigationState`. The state is fully serializable; persisting it to JSON
after every loop iteration gives us checkpoint replay for free.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class Stage(str, Enum):
    INTAKE = "intake"
    SCOPE = "scope"
    REPRODUCTION_CHECK = "reproduction_check"
    LOCATE = "locate"
    INSPECT = "inspect"
    COMPARE = "compare"
    CONFIRM_CULPRIT = "confirm_culprit"
    SUGGEST_FIX = "suggest_fix"
    DONE = "done"
    EXHAUSTED_NO_RESULT = "exhausted_no_result"


class BugReport(BaseModel):
    description: str
    symptoms: Optional[str] = None
    affected_area_hint: Optional[str] = None  # e.g. "camera", "player movement"
    stack_trace: Optional[str] = None


class BugLocation(BaseModel):
    """Where in the code the bug is — and what kind of bug it is."""
    file_path: str
    line_range: tuple[int, int]
    code_snippet: str
    bug_type: Literal["introduced", "removed", "commented_out"]
    explanation: str
    symptom_link: str
    confidence: float = Field(ge=0.0, le=1.0)


class SuspectCommit(BaseModel):
    sha: str
    short_sha: str
    author: str
    date: datetime
    message: str
    files_changed: list[str] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=list)  # all branches this commit lives on
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    rationale: str = ""
    bug_location: Optional[BugLocation] = None  # populated by Locate stage
    status: Literal["unexamined", "ruled_out", "culprit"] = "unexamined"


class FixProposal(BaseModel):
    file_path: str
    line_range: tuple[int, int]
    current_code: str
    proposed_change: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    approved_by_user: bool = False


class CheckpointResult(BaseModel):
    name: str
    passed: bool
    explanation: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class InvestigationState(BaseModel):
    """The complete state of one bug investigation. Persisted to JSON after every stage."""

    investigation_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Inputs
    bug_report: BugReport
    repo_path: str
    lookback_days: Literal[30, 90] = 30
    file_extension_scope: list[str] = Field(default_factory=lambda: [".cs", ".shader"])

    # Loop state
    current_stage: Stage = Stage.INTAKE
    focus_topic: str = ""  # used by FOCUS_LOCK guardrail

    # Discovered material
    candidate_commits: list[SuspectCommit] = Field(default_factory=list)
    eliminated_shas: set[str] = Field(default_factory=set)  # ruled-out commits, never re-propose
    reproduced: Optional[bool] = None
    fix_proposal: Optional[FixProposal] = None

    # Pillar histories
    checkpoint_history: list[CheckpointResult] = Field(default_factory=list)
    alarm_history: list[dict[str, Any]] = Field(default_factory=list)  # serialized Alarms

    # Resource accounting (drives the guardrails)
    spend_used: float = 0.0
    tokens_used: int = 0
    calls_made: int = 0
    consecutive_low_confidence: int = 0  # for GIVE_UP_THRESHOLD

    # Agent identity (lets us replay with a different agent)
    agent_name: str = ""

    def confirmed_culprit(self) -> Optional[SuspectCommit]:
        for c in self.candidate_commits:
            if c.status == "culprit":
                return c
        return None

    def rule_out(self, sha: str) -> None:
        for c in self.candidate_commits:
            if c.sha == sha:
                c.status = "ruled_out"

    def confirm_culprit(self, sha: str) -> None:
        for c in self.candidate_commits:
            c.status = "culprit" if c.sha == sha else c.status
