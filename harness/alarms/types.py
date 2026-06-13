"""Alarm types and model. Pillar 4.

Every alarm is structured: name, severity, context, recommended action.
Also emitted as an OpenTelemetry event on the active span (see bus.py).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AlarmType(str, Enum):
    # Resource exhaustion
    CALL_LIMIT_REACHED = "CALL_LIMIT_REACHED"
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"
    SPEND_CEILING_REACHED = "SPEND_CEILING_REACHED"
    STAGE_TIMEOUT = "STAGE_TIMEOUT"
    GAVE_UP_LOW_CONFIDENCE = "GAVE_UP_LOW_CONFIDENCE"

    # Hallucination / output validity
    HALLUCINATED_REF = "HALLUCINATED_REF"  # bad SHA or path
    HALLUCINATED_CODE = "HALLUCINATED_CODE"  # bad snippet / line range
    MISSING_SYMPTOM_LINK = "MISSING_SYMPTOM_LINK"

    # Behavioral
    OFF_TOPIC_DRIFT = "OFF_TOPIC_DRIFT"
    LOW_CONFIDENCE_NO_REPRO = "LOW_CONFIDENCE_NO_REPRO"
    RE_PROPOSED_ELIMINATED = "re_proposed_eliminated"

    # Safety
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    UNVERIFIED_FIX = "UNVERIFIED_FIX"
    AMBIGUOUS_FIX = "AMBIGUOUS_FIX"


Severity = Literal["low", "medium", "high"]


class Alarm(BaseModel):
    type: AlarmType
    severity: Severity
    context: dict[str, Any] = Field(default_factory=dict)
    recommended_action: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def dog_voice(self) -> str:
        """Render the alarm in the project's casual voice for UI display."""
        voice_map = {
            AlarmType.HALLUCINATED_REF: "Hold up dog — the agent made up a commit hash. Retrying.",
            AlarmType.HALLUCINATED_CODE: "Hold up dog — the agent cited code that isn't actually there. Retrying.",
            AlarmType.MISSING_SYMPTOM_LINK: "Yo dog, the agent didn't explain how this code causes the bug. Asking again.",
            AlarmType.SPEND_CEILING_REACHED: "Yo dog, we hit the spend ceiling. Halting investigation.",
            AlarmType.TOKEN_BUDGET_EXCEEDED: "Yo dog, out of tokens. Halting investigation.",
            AlarmType.CALL_LIMIT_REACHED: "Yo dog, the agent's been called too many times. Halting.",
            AlarmType.GAVE_UP_LOW_CONFIDENCE: "Sorry dog, couldn't sniff out the culprit with the budget we had.",
            AlarmType.OFF_TOPIC_DRIFT: "That doesn't smell like the current bug — keep sniffing this one or switch?",
            AlarmType.LOW_CONFIDENCE_NO_REPRO: "You haven't confirmed the bug reproduces — confidence capped.",
            AlarmType.RE_PROPOSED_ELIMINATED: "Hold up dog — the agent suggested something we already ruled out.",
            AlarmType.STAGE_TIMEOUT: "Stage timed out — retrying once.",
            AlarmType.SCOPE_VIOLATION: "Heads up dog — the agent tried to look outside its lane.",
            AlarmType.UNVERIFIED_FIX: "Hold up dog — the proposed fix doesn't touch the culprit's files.",
            AlarmType.AMBIGUOUS_FIX: "Yo dog, multiple plausible fixes — need you to pick one.",
        }
        return voice_map.get(self.type, str(self.type.value))
