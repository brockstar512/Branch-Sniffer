"""Checkpoint Protocol — Pillar 2 base.

A checkpoint is an explicit pass/fail gate evaluated AFTER an agent action.
The result determines whether the loop continues, retries, or escalates.
The agent's next action depends on the result — that's how we meet the
'behavior changes based on checkpoint feedback' rubric requirement.
"""
from __future__ import annotations

from typing import Any, Protocol

from harness.materials.state import CheckpointResult, InvestigationState


class Checkpoint(Protocol):
    name: str

    def evaluate(self, state: InvestigationState, output: Any) -> CheckpointResult: ...
