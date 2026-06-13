"""Semantic checkpoints — verify the agent's reasoning, not just its citations.

These catch a different failure mode: the agent points at real code but for
the wrong reason, or skips the rationale entirely.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.checkpoints.base import CheckpointResult
from harness.materials.state import FixProposal, InvestigationState, SuspectCommit


@dataclass
class SymptomExplanationPresent:
    name: str = "symptom_explanation_present"
    min_chars: int = 40  # rough floor for "not empty / not generic"

    def evaluate(self, state: InvestigationState, output: SuspectCommit) -> CheckpointResult:
        if output.bug_location is None:
            return CheckpointResult(name=self.name, passed=True, explanation="no bug_location to verify")
        loc = output.bug_location
        ok = bool(loc.symptom_link.strip()) and len(loc.symptom_link) >= self.min_chars
        return CheckpointResult(
            name=self.name,
            passed=ok,
            explanation=f"symptom_link length={len(loc.symptom_link)} (min {self.min_chars})",
        )


@dataclass
class FixTouchesCulprit:
    name: str = "fix_touches_culprit"

    def evaluate(self, state: InvestigationState, output: FixProposal) -> CheckpointResult:
        culprit = state.confirmed_culprit()
        if culprit is None:
            return CheckpointResult(name=self.name, passed=False, explanation="no culprit confirmed")
        ok = output.file_path in culprit.files_changed
        return CheckpointResult(
            name=self.name,
            passed=ok,
            explanation=f"fix touches {output.file_path}; culprit changed {culprit.files_changed}",
        )


@dataclass
class ReproductionRecorded:
    """Non-halting: if reproduction was not confirmed, downstream confidence
    will be capped. The loop reads this result and updates the state's
    consecutive_low_confidence counter / confidence ceiling accordingly.
    """
    name: str = "reproduction_recorded"

    def evaluate(self, state: InvestigationState, output: Any = None) -> CheckpointResult:
        if state.reproduced is None:
            return CheckpointResult(name=self.name, passed=False, explanation="reproduction status unknown")
        if state.reproduced is False:
            return CheckpointResult(name=self.name, passed=False, explanation="not reproduced; capping downstream confidence")
        return CheckpointResult(name=self.name, passed=True, explanation="reproduced")
