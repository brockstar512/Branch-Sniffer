"""The main loop — orchestrates the pillars.

This file should stay short and boring. All real work happens in the pillar
modules or the agent. The loop's job is:
    load state -> run guardrails -> call agent -> run checkpoints
                -> raise alarms -> persist -> repeat

PHASE 1: plain Python loop. State persists after every stage transition.
PHASE 2: optional migration to LangGraph if state-machine complexity grows.
The pillar modules will not change either way.
"""
from __future__ import annotations

from datetime import datetime

from agents.base import Agent
from harness.alarms.bus import bus
from harness.alarms.types import AlarmType
from harness.checkpoints.reference import (
    BranchExists,
    BugTypeInEnum,
    CodeSnippetExists,
    CommitExists,
    ConfidenceInRange,
    LineRangeValid,
    PathExists,
)
from harness.checkpoints.semantic import (
    FixTouchesCulprit,
    ReproductionRecorded,
    SymptomExplanationPresent,
)
from harness.guardrails.base import Guardrail
from harness.guardrails.focus import FocusLock
from harness.guardrails.resource import (
    CallLimit,
    GiveUpThreshold,
    SpendCeiling,
    TokenBudget,
)
from harness.guardrails.safety import (
    FileExtensionScope,
    NoAutoApply,
    ReadOnlyRepo,
    WindowBound,
)
from harness.materials.state import InvestigationState, Stage
from harness.materials.store import save
from harness.telemetry.tracer import get_tracer, init_telemetry

MIN_CONFIDENCE_TO_PROPOSE = 0.4


def _default_guardrails() -> list[Guardrail]:
    return [
        CallLimit(),
        TokenBudget(),
        SpendCeiling(),
        GiveUpThreshold(),
        ReadOnlyRepo(),
        NoAutoApply(),
        WindowBound(),
        FileExtensionScope(),
        FocusLock(),
    ]


def _run_guardrails(state: InvestigationState, guardrails: list[Guardrail]) -> bool:
    """Returns True if all passed. Raises alarms and updates state on failures."""
    tracer = get_tracer()
    all_ok = True
    for g in guardrails:
        with tracer.start_as_current_span(f"guardrail.{g.name}") as span:
            r = g.check(state)
            span.set_attribute("result", "pass" if r.passed else "fail")
            span.set_attribute("explanation", r.explanation)
            state.guardrail_history.append(
                {
                    "name": r.name,
                    "passed": r.passed,
                    "explanation": r.explanation,
                    "stage": state.current_stage.value,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
            )
            if not r.passed:
                all_ok = False
                # Map guardrail -> alarm
                alarm_map = {
                    "CALL_LIMIT": AlarmType.CALL_LIMIT_REACHED,
                    "TOKEN_BUDGET": AlarmType.TOKEN_BUDGET_EXCEEDED,
                    "SPEND_CEILING": AlarmType.SPEND_CEILING_REACHED,
                    "GIVE_UP_THRESHOLD": AlarmType.GAVE_UP_LOW_CONFIDENCE,
                    "READ_ONLY_REPO": AlarmType.SCOPE_VIOLATION,
                    "WINDOW_BOUND": AlarmType.SCOPE_VIOLATION,
                    "FILE_EXTENSION_SCOPE": AlarmType.SCOPE_VIOLATION,
                }
                alarm_type = alarm_map.get(g.name, AlarmType.SCOPE_VIOLATION)
                severity = "high" if alarm_type != AlarmType.GAVE_UP_LOW_CONFIDENCE else "medium"
                bus.raise_alarm(
                    state,
                    type=alarm_type,
                    severity=severity,
                    recommended_action="halt + escalate" if severity == "high" else "return inconclusive",
                    context={"guardrail": g.name, "detail": r.explanation},
                )
    return all_ok


def run(state: InvestigationState, agent: Agent) -> InvestigationState:
    """Run the loop end-to-end on an initial state. Returns the final state.

    In Phase 1 every stage is a thin wrapper that calls the agent stub, runs
    relevant checkpoints, and advances. Real per-stage logic is filled in in
    Phase 2.
    """
    init_telemetry()
    tracer = get_tracer()
    state.agent_name = agent.name

    with tracer.start_as_current_span("loop") as loop_span:
        loop_span.set_attribute("investigation_id", state.investigation_id)
        loop_span.set_attribute("agent", agent.name)

        guardrails = _default_guardrails()

        # --- INTAKE ---
        state.current_stage = Stage.INTAKE
        with tracer.start_as_current_span("stage.intake"):
            if not _run_guardrails(state, guardrails):
                save(state)
                return state
            save(state)

        # --- SCOPE ---
        state.current_stage = Stage.SCOPE
        with tracer.start_as_current_span("stage.scope"):
            if not _run_guardrails(state, guardrails):
                save(state)
                return state
            candidates = agent.propose_candidates(state)
            state.calls_made += 1
            usage = getattr(agent, "_last_usage", {})
            state.tokens_used += int(usage.get("tokens", 0))
            state.spend_used += float(usage.get("cost", 0.0))

            # Drop any candidate the user already ruled out, alarming on each.
            re_proposed = [c for c in candidates if c.sha in state.eliminated_shas]
            for c in re_proposed:
                bus.raise_alarm(
                    state,
                    type=AlarmType.RE_PROPOSED_ELIMINATED,
                    severity="high",
                    recommended_action="drop and continue",
                    context={"sha": c.sha, "short_sha": c.short_sha},
                )
            candidates = [c for c in candidates if c.sha not in state.eliminated_shas]

            candidates = [
                c for c in candidates if c.confidence >= MIN_CONFIDENCE_TO_PROPOSE
            ]
            state.candidate_commits = candidates

            if not candidates:
                state.current_stage = Stage.EXHAUSTED_NO_RESULT
                save(state)
                return state

            # Reference checkpoints on the proposed candidates
            for cp in (CommitExists(), PathExists()):
                cr = cp.evaluate(state, candidates)
                state.checkpoint_history.append(cr)
                if not cr.passed:
                    bus.raise_alarm(
                        state,
                        type=AlarmType.HALLUCINATED_REF,
                        severity="high",
                        recommended_action="retry stage",
                        context={"checkpoint": cp.name, "detail": cr.explanation},
                    )
            save(state)

        # --- REPRODUCTION CHECK ---
        state.current_stage = Stage.REPRODUCTION_CHECK
        with tracer.start_as_current_span("stage.reproduction_check"):
            cr = ReproductionRecorded().evaluate(state)
            state.checkpoint_history.append(cr)
            if not cr.passed and state.reproduced is False:
                bus.raise_alarm(
                    state,
                    type=AlarmType.LOW_CONFIDENCE_NO_REPRO,
                    severity="medium",
                    recommended_action="recommend reproduction",
                )
            save(state)

        # --- LOCATE ---
        state.current_stage = Stage.LOCATE
        with tracer.start_as_current_span("stage.locate"):
            if not _run_guardrails(state, guardrails):
                save(state)
                return state
            for commit in state.candidate_commits:
                loc = agent.locate_bug(state, commit)
                state.calls_made += 1
                usage = getattr(agent, "_last_usage", {})
                state.tokens_used += int(usage.get("tokens", 0))
                state.spend_used += float(usage.get("cost", 0.0))
                commit.bug_location = loc

                for cp in (
                    CodeSnippetExists(),
                    LineRangeValid(),
                    SymptomExplanationPresent(),
                    BranchExists(),
                    ConfidenceInRange(),
                    BugTypeInEnum(),
                ):
                    cr = cp.evaluate(state, commit)
                    state.checkpoint_history.append(cr)
                    if not cr.passed:
                        # Map checkpoint -> alarm
                        if cp.name in ("code_snippet_exists", "line_range_valid"):
                            atype = AlarmType.HALLUCINATED_CODE
                        elif cp.name == "symptom_explanation_present":
                            atype = AlarmType.MISSING_SYMPTOM_LINK
                        else:
                            atype = AlarmType.HALLUCINATED_REF
                        bus.raise_alarm(
                            state,
                            type=atype,
                            severity="high" if atype != AlarmType.MISSING_SYMPTOM_LINK else "medium",
                            recommended_action="retry Locate",
                            context={"sha": commit.short_sha, "checkpoint": cp.name},
                        )
            save(state)

        # Phase 1 stops here. Subsequent stages (inspect, compare, confirm, fix)
        # are driven by user interaction in the Streamlit app and will be added
        # in Phases 4–5.

        state.current_stage = Stage.DONE
        save(state)

    return state
