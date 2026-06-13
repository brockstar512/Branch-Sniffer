# HARNESS.md — Branch Sniffer Verification Harness

## 1. Overview

**Branch Sniffer** ("dog") is a bug-investigation tool for Unity/Git repositories. Given a
bug report (description, optional stack trace, optional affected-area hint), it scans the
most recently active branches within a lookback window, asks an LLM agent to rank the
commits most likely to have introduced the bug, then locates the offending file/line/
reasoning inside each suspect commit — and verifies every claim the agent makes against
the real repository before showing it to a human.

The **harness** is the verification scaffold *around* the agent — it is **not** the agent.
The agent is a swappable component (`agents/base.py:Agent`) that proposes commits and
locates bugs. The harness is everything that constrains, checks, records, and reports on
that agent: the guardrails that run before each agent call, the checkpoints that validate
each agent output, the materials (state) that flow through, the alarms that fire on
failure, the telemetry that traces it all, and the loop that orchestrates them. The agent
can hallucinate; the harness exists to catch it when it does. Swapping `ClaudeAgent` for
`GrepAgent` changes *who does the thinking* but not *how the thinking is policed*.

## 2. The Four Pillars

Each pillar is a package under `harness/` with a Protocol/base type and concrete
implementations. The loop (`harness/loop.py`) wires them together.

### Pillar 1 — Guardrails (`harness/guardrails/`)

**Purpose:** declared constraints evaluated **before** the agent acts. A guardrail failure
halts the loop (high severity) or routes to an inconclusive result. Base Protocol:
`harness/guardrails/base.py:Guardrail` — every guardrail implements
`check(state) -> GuardrailResult`.

There are **9** concrete guardrails, all wired in `loop.py:_default_guardrails()`:

| Guardrail | File | Purpose |
|-----------|------|---------|
| `CallLimit` | `resource.py` | Halts when `calls_made >= 20` (default limit). |
| `TokenBudget` | `resource.py` | Halts when `tokens_used >= 200_000`. |
| `SpendCeiling` | `resource.py` | Halts when `spend_used >= $2.00`. |
| `GiveUpThreshold` | `resource.py` | Halts after 3 consecutive low-confidence attempts. |
| `ReadOnlyRepo` | `safety.py` | Verifies the repo path exists and is a `.git` directory; declares read-only enforcement. |
| `NoAutoApply` | `safety.py` | Declares that no fix-apply pathway exists; trips if one is ever added. |
| `WindowBound` | `safety.py` | Confirms `lookback_days` is one of the allowed windows (30, 90). |
| `FileExtensionScope` | `safety.py` | Confirms the configured extension scope (default `.cs`, `.shader`) is sane. |
| `FocusLock` | `focus.py` | Intended to intercept off-topic user messages — **currently a stub** (see §9). |

`resource.py` also declares `RETRY_LIMIT = 3` and `TIMEOUT_PER_STAGE_SECONDS = 60.0` as
module constants for visibility; these are per-stage and not enforced as guardrail objects.

### Pillar 2 — Checkpoints (`harness/checkpoints/`)

**Purpose:** explicit pass/fail gates evaluated **after** an agent action. The result
determines whether the loop continues, retries, or escalates. Base Protocol:
`harness/checkpoints/base.py:Checkpoint` — every checkpoint implements
`evaluate(state, output) -> CheckpointResult`.

**Reference checkpoints** (`reference.py`) — catch the agent citing things that don't exist
(all run real read-only git commands via `_git()`):

- `CommitExists` — each cited SHA resolves to a commit (`git cat-file -t`).
- `PathExists` — each cited file path exists at that commit (`git ls-tree`).
- `CodeSnippetExists` — type-aware: the cited snippet actually appears. For `introduced`
  it must be in the file at the commit; for `removed` it must be in the parent but not the
  commit; for `commented_out` it must appear as a comment line.
- `LineRangeValid` — the cited `(start, end)` fits within the file's line count.
- `DiffNonempty` — meant to confirm diff summaries reference real hunks — **stub** (§9).

**Semantic checkpoints** (`semantic.py`) — catch real code cited for the wrong reason:

- `SymptomExplanationPresent` — the `symptom_link` is non-empty and ≥ 40 chars.
- `FixTouchesCulprit` — a proposed fix's file is among the confirmed culprit's changed files.
- `ReproductionRecorded` — non-halting; reports whether reproduction was confirmed so
  downstream confidence can be capped.

### Pillar 3 — Materials (`harness/materials/state.py`)

**Purpose:** the single serializable source of truth flowing through every pillar.
Persisted to JSON after every stage (`harness/materials/store.py:save`).

Pydantic models in `state.py`:

- `Stage` (enum) — the loop's stage values (see §4).
- `BugReport` — `description`, `symptoms?`, `affected_area_hint?`, `stack_trace?`.
- `BugLocation` — `file_path`, `line_range`, `code_snippet`, `bug_type`
  (`introduced|removed|commented_out|legacy`), `explanation`, `symptom_link`,
  `call_context`, `confidence`.
- `SuspectCommit` — `sha`, `short_sha`, `author`, `date`, `message`, `files_changed`,
  `branches`, `confidence`, `rationale`, `bug_location?`, `status`
  (`unexamined|ruled_out|culprit`).
- `FixProposal` — `file_path`, `line_range`, `current_code`, `proposed_change`,
  `rationale`, `confidence`, `approved_by_user`.
- `CheckpointResult` — `name`, `passed`, `explanation`, `timestamp`.
- `InvestigationState` — the root aggregate: inputs (`bug_report`, `repo_path`,
  `lookback_days`, `file_extension_scope`), loop state (`current_stage`, `focus_topic`),
  discovered material (`candidate_commits`, `eliminated_shas`, `reproduced`,
  `fix_proposal`), histories (`checkpoint_history`, `alarm_history`), resource accounting
  (`spend_used`, `tokens_used`, `calls_made`, `consecutive_low_confidence`), and
  `agent_name`. Helper methods: `confirmed_culprit()`, `rule_out(sha)`,
  `confirm_culprit(sha)`.

### Pillar 4 — Alarms (`harness/alarms/`)

**Purpose:** structured failure signals. Raised via `harness/alarms/bus.py:bus.raise_alarm`,
which (1) appends to `state.alarm_history`, (2) emits an OpenTelemetry span event on the
active span, and (3) prints in the project's casual "dog voice" for CLI visibility.

Severity is **not intrinsic** to the alarm type — it is supplied at raise-time by the
caller (`Severity = "low" | "medium" | "high"`). The table below lists all **14**
`AlarmType` values from `harness/alarms/types.py` with the severity used at their current
call site in `loop.py` (or "not fired" where no call site exists yet — see §9):

| AlarmType | Severity (at raise site) |
|-----------|--------------------------|
| `CALL_LIMIT_REACHED` | high |
| `TOKEN_BUDGET_EXCEEDED` | high |
| `SPEND_CEILING_REACHED` | high |
| `STAGE_TIMEOUT` | not fired (no timeout enforcement in loop) |
| `GAVE_UP_LOW_CONFIDENCE` | medium |
| `HALLUCINATED_REF` | high |
| `HALLUCINATED_CODE` | high |
| `MISSING_SYMPTOM_LINK` | medium |
| `OFF_TOPIC_DRIFT` | not fired (FocusLock is a stub) |
| `LOW_CONFIDENCE_NO_REPRO` | medium |
| `RE_PROPOSED_ELIMINATED` | not fired (defined, no call site) |
| `SCOPE_VIOLATION` | high |
| `UNVERIFIED_FIX` | not fired (fix stage not in current loop) |
| `AMBIGUOUS_FIX` | not fired (fix stage not in current loop) |

## 3. The Agent Protocol

`agents/base.py:Agent` is a `typing.Protocol` — the swappable interface. The harness
imports **only this Protocol**; the loop never references a concrete agent directly. It
requires **five** methods:

- `propose_candidates(state) -> list[SuspectCommit]`
- `locate_bug(state, commit) -> BugLocation`
- `compare_commits(sha_a, sha_b, repo_path) -> DiffSummary`
- `suggest_fix(state) -> FixProposal`
- `reply_to_user(state, message) -> str`

The loop accepts any object satisfying this Protocol. Two concrete agents ship:

- **`ClaudeAgent`** (`agents/claude_agent.py`) — primary LLM-backed worker. Reads git-log
  metadata, asks Claude (default `claude-sonnet-4-5`) to rank suspects and locate bugs,
  and records token/cost usage in `_last_usage` (read back into state by the loop).
- **`GrepAgent`** (`agents/grep_agent.py`) — deterministic, no-LLM, $0-cost worker for
  the portability bonus. It never hallucinates SHAs or code, but its templated rationale
  trips `MISSING_SYMPTOM_LINK` by design.

Swap agents by changing the construction in the entry point (`cli.py --agent claude|grep`,
or `app/streamlit_app.py`).

## 4. The Investigation Loop

`harness/loop.py:run(state, agent)` drives the investigation. The `Stage` enum
(`state.py`) defines the stage values: `INTAKE`, `SCOPE`, `REPRODUCTION_CHECK`, `LOCATE`,
`INSPECT`, `COMPARE`, `CONFIRM_CULPRIT`, `SUGGEST_FIX`, `DONE`, `EXHAUSTED_NO_RESULT`.

The current loop implements the first four working stages plus terminal states. At each
stage it runs guardrails, calls the agent, runs the relevant checkpoints, raises alarms on
failure, and persists state. The `INSPECT`/`COMPARE`/`CONFIRM_CULPRIT`/`SUGGEST_FIX`
stages are defined in the enum but driven by user interaction in the Streamlit app rather
than the core loop.

```
              ┌──────────┐
              │  INTAKE  │  guardrails
              └────┬─────┘
                   │ pass
              ┌────▼─────┐
              │  SCOPE   │  propose_candidates → CommitExists, PathExists
              └────┬─────┘
        no suspects│  │ suspects (confidence ≥ 0.4)
       ┌───────────┘  │
┌──────▼───────────┐  │
│ EXHAUSTED_NO_    │  │
│ RESULT (terminal)│  │
└──────────────────┘  │
              ┌───────▼──────────┐
              │ REPRODUCTION_    │  ReproductionRecorded (non-halting)
              │ CHECK            │
              └───────┬──────────┘
              ┌───────▼──────────┐
              │     LOCATE       │  locate_bug → CodeSnippetExists,
              │                  │  LineRangeValid, SymptomExplanationPresent
              └───────┬──────────┘
              ┌───────▼──────────┐
              │  DONE (terminal) │
              └──────────────────┘

  Any guardrail failure (high severity) → save + early return (halt).
```

There is no dedicated `ABORTED` stage: a high-severity guardrail failure raises an alarm,
saves state, and returns early from `run()` with `current_stage` left at the stage that
tripped. The two explicit terminal stages are `DONE` and `EXHAUSTED_NO_RESULT`.

## 5. Multi-turn Continuation

Implemented in `app/streamlit_app.py` (the core loop itself is single-shot). The Streamlit
session accumulates conversation context across turns:

- `st.session_state.turns` is a list; each `_run_turn()` appends
  `{"user_input", "state": final}` (line ~140), so prior results stay visible.
- Eliminated branches: when the user rules out a branch, it is added to
  `st.session_state.eliminated_branches` (line ~318). Before each turn, `_branch_shas()`
  converts those branch names to a full set of commit SHAs via
  `git rev-list <branch> --since=<window>` (lines 85–102), assigned to
  `state.eliminated_shas` so the agent's git-log scan drops them.
- Rejected reasoning: user notes are appended to `st.session_state.rejected_notes`
  (line ~325). `_effective_description()` (lines 105–109) folds `description`,
  follow-up `refinements`, and `rejected_notes` into the next turn's `BugReport.description`,
  so the agent sees what was already rejected.

**Honest limitation (by design):** each turn builds a **fresh** `InvestigationState`
(`_run_turn`, lines 112–124), so every turn gets a **new `investigation_id`**.
`checkpoint_history` and `alarm_history` do **not** persist across turns — only the
distilled context (`eliminated_shas` + enriched `description`) carries forward. Each turn
is a clean investigation enriched with prior eliminations and rejections, not a resumption
of the previous one. This is a deliberate trade-off: it keeps state serialization simple
and avoids replaying stale checkpoints, at the cost of cross-turn history continuity.

## 6. Telemetry

`harness/telemetry/tracer.py` sets up OpenTelemetry. `init_telemetry()` is idempotent and
called once at process start; it uses the console exporter by default (zero infra) and
ships to OTLP when `DOG_OTLP_ENDPOINT` is set. Service name is `dog`.

Span hierarchy emitted by `loop.py`:

```
loop                                  (top span; investigation_id, agent attrs)
├── stage.intake
│   └── guardrail.<NAME>              (one span per guardrail check)
├── stage.scope
│   └── guardrail.<NAME> ...
├── stage.reproduction_check
└── stage.locate
    └── guardrail.<NAME> ...
```

Each `guardrail.<name>` span carries `result` (`pass`/`fail`) and `explanation`
attributes. Alarms are **not** separate spans — `bus.raise_alarm` emits them as span
**events** (`alarm.<TYPE>`) on whichever stage span is active when they fire
(`harness/alarms/bus.py`, lines 39–49), with `severity`, `recommended_action`, and
`ctx.*` attributes.

## 7. Read-Only Enforcement

The `ReadOnlyRepo` guardrail (`harness/guardrails/safety.py`) asserts read-only operation:
it verifies `repo_path` exists and is a git directory, and declares the constraint. The
companion `NoAutoApply` guardrail declares that no fix-apply pathway exists and trips if
one is ever added.

Every git invocation in the codebase is a **read-only** subcommand. The full set actually
used across `agents/` and `harness/` is:

- `for-each-ref` — enumerate recent branches (`claude_agent.py`).
- `rev-list` — list/count commits on a branch within the window (`claude_agent.py`,
  `app/streamlit_app.py`).
- `log` — read commit metadata (`claude_agent.py`).
- `show` — read file contents at a commit (`reference.py`, used 6×).
- `cat-file` — resolve a SHA's type (`reference.py:CommitExists`).
- `ls-tree` — confirm a path exists at a commit (`reference.py:PathExists`).

No write subcommand (`add`, `commit`, `checkout`, `reset`, `push`, `merge`, `apply`,
`clean`, `rm`, `stash`, …) appears anywhere in the codebase. (The single textual match for
`"commit"` is the *type string* returned by `git cat-file -t`, not the command.)

## 8. Honest Termination

The harness refuses to manufacture suspects:

- `loop.py` defines `MIN_CONFIDENCE_TO_PROPOSE = 0.4`. After `propose_candidates`, the loop
  filters out every candidate below that floor (`loop.py:129–131`).
- The agent prompt instructs Claude to **return an empty list `[]`** when no candidate is
  plausibly above 0.4 confidence — *"Do not manufacture suspects"* (`claude_agent.py`,
  the `_rank_with_claude` prompt).
- If no candidate survives the floor, the loop transitions to `Stage.EXHAUSTED_NO_RESULT`,
  saves, and returns (`loop.py:134–137`). This is a first-class terminal state — "we
  couldn't find it" is a valid, honest outcome, not an error.

## 9. Known Gaps and Design Choices

Stated plainly:

- **`FocusLock` is a stub.** `harness/guardrails/focus.py` hard-codes "on topic" and its
  docstring says so; the LLM classifier is not wired. Consequently `OFF_TOPIC_DRIFT` never
  fires.
- **`DiffNonempty` is a stub.** `harness/checkpoints/reference.py:DiffNonempty.evaluate`
  returns `passed=True` with explanation `"stub"`.
- **`GrepAgent.propose_candidates` returns `[]`.** The deterministic agent's candidate
  proposal is deferred (Phase 6 follow-up); `locate_bug`/`suggest_fix` return templated
  low-confidence output by design.
- **`RE_PROPOSED_ELIMINATED` is defined but never fired.** The alarm type exists in
  `types.py` (with dog-voice text) but has no call site in the current loop;
  re-proposal is instead prevented upstream by `eliminated_shas` filtering.
- **Multi-turn does not persist checkpoint/alarm history across turns.** Each turn is a
  fresh investigation (new `investigation_id`) enriched with prior `eliminated_branches`
  (→ `eliminated_shas`) and `rejected_notes` (→ description). See §5.
- **No retry on checkpoint failure in Locate.** When a checkpoint fails in the `LOCATE`
  stage, the loop raises the appropriate alarm and continues — it does not loop back and
  re-ask the agent. The `recommended_action` strings (e.g. `"retry Locate"`) and the
  `RETRY_LIMIT`/`TIMEOUT_PER_STAGE_SECONDS` constants are **advisory** in the current
  implementation, not enforced control flow.
