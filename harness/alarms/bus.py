"""AlarmBus — central point for raising alarms.

When an alarm is raised:
  1. It's appended to the investigation state's alarm_history
  2. It's emitted as an OpenTelemetry event on the active span
  3. It's printed to stdout in the dog voice for CLI visibility
"""
from __future__ import annotations

from typing import Any

from opentelemetry import trace

from harness.alarms.types import Alarm, AlarmType, Severity
from harness.materials.state import InvestigationState


class AlarmBus:
    """Singleton-style bus. Pass it the state; it knows what to do with alarms."""

    def raise_alarm(
        self,
        state: InvestigationState,
        type: AlarmType,
        severity: Severity,
        recommended_action: str,
        context: dict[str, Any] | None = None,
    ) -> Alarm:
        alarm = Alarm(
            type=type,
            severity=severity,
            context=context or {},
            recommended_action=recommended_action,
        )

        # 1. Persist into state
        state.alarm_history.append(alarm.model_dump(mode="json"))

        # 2. Emit OpenTelemetry event on the active span
        span = trace.get_current_span()
        if span is not None:
            span.add_event(
                name=f"alarm.{type.value}",
                attributes={
                    "severity": severity,
                    "recommended_action": recommended_action,
                    **{f"ctx.{k}": str(v) for k, v in (context or {}).items()},
                },
            )

        # 3. Print for CLI visibility (Streamlit will render from alarm_history instead)
        print(f"  [ALARM/{severity.upper()}] {alarm.dog_voice()}")

        return alarm


# Module-level singleton for convenience
bus = AlarmBus()
