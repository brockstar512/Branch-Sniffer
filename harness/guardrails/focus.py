"""FocusLock guardrail — intercepts off-topic user messages.

The full implementation calls a cheap LLM classifier to decide whether a
user's message relates to the current focus_topic. This stub just hard-codes
"on topic" so the loop runs in Phase 1. Replace `check()` once the agents
package has a `classify_topic` helper.
"""
from __future__ import annotations

from dataclasses import dataclass

from harness.guardrails.base import GuardrailResult
from harness.materials.state import InvestigationState


@dataclass
class FocusLock:
    name: str = "FOCUS_LOCK"

    def check(self, state: InvestigationState) -> GuardrailResult:
        # TODO: classifier call against most-recent user message
        return GuardrailResult(
            name=self.name,
            passed=True,
            explanation="stub: classifier not yet wired",
        )

    def is_on_topic(self, message: str, focus_topic: str) -> bool:
        """Called by the loop when a user message arrives mid-investigation."""
        # TODO: replace with a cheap LLM classifier
        # For now, return True if the message shares any keyword > 3 chars with the focus
        focus_words = {w.lower() for w in focus_topic.split() if len(w) > 3}
        msg_words = {w.lower() for w in message.split() if len(w) > 3}
        return not focus_words or bool(focus_words & msg_words)
