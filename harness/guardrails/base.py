"""Guardrail Protocol — Pillar 1 base.

A guardrail is a declared constraint, evaluated BEFORE the agent acts.
Every guardrail implements `check(state) -> GuardrailResult`.
The loop calls all guardrails before any agent call; a failure halts or alerts.
"""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from harness.materials.state import InvestigationState


class GuardrailResult(BaseModel):
    name: str
    passed: bool
    explanation: str = ""


class Guardrail(Protocol):
    name: str

    def check(self, state: InvestigationState) -> GuardrailResult: ...
