"""Resource-limit guardrails — primary control surface.

Each is a declared constraint with a default that can be overridden via constructor.
Tripping any of these halts the loop and routes to an inconclusive result.
"""
from __future__ import annotations

from dataclasses import dataclass

from harness.guardrails.base import GuardrailResult
from harness.materials.state import InvestigationState


@dataclass
class CallLimit:
    name: str = "CALL_LIMIT"
    limit: int = 20

    def check(self, state: InvestigationState) -> GuardrailResult:
        ok = state.calls_made < self.limit
        return GuardrailResult(
            name=self.name,
            passed=ok,
            explanation=f"calls_made={state.calls_made} / limit={self.limit}",
        )


@dataclass
class TokenBudget:
    name: str = "TOKEN_BUDGET"
    limit: int = 200_000

    def check(self, state: InvestigationState) -> GuardrailResult:
        ok = state.tokens_used < self.limit
        return GuardrailResult(
            name=self.name,
            passed=ok,
            explanation=f"tokens_used={state.tokens_used} / limit={self.limit}",
        )


@dataclass
class SpendCeiling:
    name: str = "SPEND_CEILING"
    limit_usd: float = 2.00

    def check(self, state: InvestigationState) -> GuardrailResult:
        ok = state.spend_used < self.limit_usd
        return GuardrailResult(
            name=self.name,
            passed=ok,
            explanation=f"spend_used=${state.spend_used:.4f} / limit=${self.limit_usd:.2f}",
        )


@dataclass
class GiveUpThreshold:
    name: str = "GIVE_UP_THRESHOLD"
    limit: int = 3  # consecutive low-confidence attempts before halt

    def check(self, state: InvestigationState) -> GuardrailResult:
        ok = state.consecutive_low_confidence < self.limit
        return GuardrailResult(
            name=self.name,
            passed=ok,
            explanation=f"consecutive_low_confidence={state.consecutive_low_confidence} / limit={self.limit}",
        )


# Note: RETRY_LIMIT and TIMEOUT_PER_STAGE are enforced inline in the loop
# because they're per-stage rather than per-investigation, but they're
# still declared constants here for visibility.
RETRY_LIMIT: int = 3
TIMEOUT_PER_STAGE_SECONDS: float = 60.0
