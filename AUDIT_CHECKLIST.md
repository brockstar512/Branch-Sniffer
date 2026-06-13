# Branch Sniffer — Architecture & Code Quality Audit Checklist

## Purpose of this document

This is a **rigorous audit checklist** for evaluating whether the Branch Sniffer codebase (`/Users/marshallbrock/Desktop/Gauntlet/dog`) is a **fully reliable agentic tool** built around a real harness, or whether it's **"vibe code"** — a thin Streamlit wrapper around prompt-engineered LLM calls dressed up to look like infrastructure.

The reviewer should walk through every section, perform the listed verifications against the actual code (not against this document's claims about the code), and produce a section-by-section verdict. **Do not take the author's word for anything.** Every claim must be grounded in a specific file path, line range, function name, or executable command that demonstrates the property.

At the end, render a final verdict per pillar (Vibe / Mixed / Reliable) and an overall verdict, with explicit citations to code locations supporting each judgment.

---

## The Original Rubric

The build challenge required an AI-governed harness for bug investigation, evaluated against **four pillars that must exist as demonstrably separate modules** — not as inline checks scattered through agent calls. The pillars are:

1. **Guardrails** — *preventive* constraints checked **before** an agent action runs. They prevent the agent from doing things that would be out of scope, dangerous, or expensive.
2. **Checkpoints** — *verification* gates that inspect agent **output** after it is produced, before that output is allowed to influence downstream state. They detect hallucinations, schema violations, and semantic incoherence.
3. **Materials** — *state and working memory* that persists across stages and turns, separate from the agent's prompt context. Inspectable, durable, and the source of truth for the investigation.
4. **Alarms** — *anomaly signals* with severity and recommended action, raised when something the agent did or said is suspect. They are the audit trail that proves the harness caught things, not the agent.

Additional non-negotiable requirements:

- A `HARNESS.md` document describing the harness design.
- A **multi-turn loop** — the same investigation continues across multiple agent invocations with shared state.
- A **swappable agent** — a `Protocol` or `ABC` such that a second agent (in this project: `GrepAgent` or `StubAgent`) can be substituted with no harness changes.
- Honest termination — when no candidate meets the confidence floor, the loop terminates in `EXHAUSTED_NO_RESULT` rather than fabricating a suspect.
- Read-only repo access — the harness never modifies the user's git history.

**Bonus credit:** a second worker actually wired in and demonstrably swappable.

---

## How to use this checklist

For each pillar section:

1. **Read the requirement.**
2. **Run the verification commands** (or hand-equivalent inspections) listed.
3. **Compare against the "Reliable markers" and "Vibe red flags" lists.**
4. **Record findings with file:line citations.**
5. **Produce a section verdict.**

Use `rg` (ripgrep) or `grep -rn` to scan. Always check the actual current state of the repo, not stale assumptions.

---

## Pillar 1 — Guardrails

### Requirement

Guardrails are **preventive**, **declarative**, and **enforced before every agent action**. Each guardrail is its own concrete type with a unique identifier; each evaluation returns a structured result (not a boolean) carrying both the verdict and an explanation. Guardrails must fail closed: an unknown or error state must not be silently treated as a pass.

The original plan listed **9 guardrails**:

1. `CALL_LIMIT` — cap total agent calls per investigation
2. `TOKEN_BUDGET` — cap total tokens consumed
3. `SPEND_CEILING` — cap dollar spend
4. `GIVE_UP_THRESHOLD` — terminate after N consecutive low-confidence results
5. `READ_ONLY_REPO` — never write to the user's git repo
6. `NO_AUTO_APPLY` — never apply a suggested fix automatically
7. `WINDOW_BOUND` — restrict lookback window (e.g., 30–90 days)
8. `FILE_EXTENSION_SCOPE` — restrict to specific extensions (`.cs`, `.shader`)
9. `FOCUS_LOCK` — keep the agent on-task (originally a Haiku classifier; may be stubbed)

### Files that must exist

- `harness/guardrails/` directory (not a single flat file)
- A `base.py` (or equivalent) defining the abstract `Guardrail` interface
- Concrete subclass files (e.g., `resource.py`, `safety.py`, `focus.py`) grouping related guardrails

### Verification commands

```bash
# Check the directory layout
ls -la harness/guardrails/

# Confirm a base type exists
rg -l "class.*Guardrail" harness/guardrails/

# Count the concrete guardrail implementations
rg "class \w+Guardrail" harness/guardrails/ | wc -l

# Verify guardrails are evaluated BEFORE the agent runs in each stage
rg -n "evaluate_guardrails\|guardrail" harness/loop.py

# Find where guardrail results are recorded
rg -n "GuardrailResult\|guardrail_result" harness/

# Confirm each guardrail returns a structured result, not a bool
rg -A 3 "def evaluate" harness/guardrails/
```

### Specific behavioral checks

1. **Each guardrail has a unique identifier (enum or class-level constant).** If guardrails are addressed only by string name with no enum/registry, that is a vibe pattern.

2. **Guardrails run before every agent call**, not just once at investigation start. Open `harness/loop.py` and confirm guardrail evaluation is invoked at each stage boundary (intake, scope, locate, etc.), not exclusively in `__init__`.

3. **Each guardrail result is persisted into materials/state**. Look for a `guardrail_history` or equivalent list on `InvestigationState`, written every time guardrails run. If results are computed and discarded, the harness has no audit trail and the pillar fails.

4. **The result carries both a verdict and an explanation string**. A bare `True`/`False` return is a vibe pattern.

5. **`READ_ONLY_REPO` actually enforces something**. Inspect its implementation: does it check that the repo path exists and is a git repo (yes/no)? Does it confirm no write operations have been issued? Or does it always return `pass`? An always-pass guardrail is theatre.

6. **`SPEND_CEILING` and `TOKEN_BUDGET` read live counters**, not stubs. Trace where `state.spend_used` and `state.tokens_used` are mutated. If those counters are never incremented from real agent usage data, the spend guardrail is fictional even if its evaluation function looks sensible.

7. **`FOCUS_LOCK` honesty**. If this guardrail is stubbed (returns "stub: classifier not yet wired" or similar), that should be **explicitly acknowledged in the explanation field** so the audit trail reflects the truth. A stub that returns a fake pass without admitting it is a vibe red flag.

8. **Failure mode**: what happens when a guardrail fails? Open the loop and trace the flow. The investigation must transition to an `aborted` or terminal state with the failure recorded, not silently continue.

### Vibe red flags

- Guardrail checks scattered inline as `if`-statements in `loop.py` instead of dedicated classes
- A single mega-function called `check_guardrails` that does everything
- No base class — every "guardrail" is a function returning `True`/`False`
- Guardrails defined but never invoked, or invoked only once at startup
- Results not persisted; no way to ask "did `SPEND_CEILING` pass at stage X?" after the run
- Stub guardrails that return fake passes without admitting it

### Reliable markers

- One file per logical guardrail group
- Base `Guardrail` abstract class with `evaluate(state) -> GuardrailResult`
- `GuardrailResult` is a Pydantic/dataclass with `name`, `result`, `explanation`
- Loop invokes guardrails at every stage transition
- Each evaluation creates an OTel span with attributes
- Stubs (like `FOCUS_LOCK`) honestly label themselves as stubs in the explanation
- Failure → terminal state with reason captured in materials

### Verdict criteria

- **Reliable**: 7+ of the 9 are real (non-stub) implementations, all run pre-stage, results persisted, base class exists, structured results.
- **Mixed**: 4–6 real implementations OR results not consistently persisted OR base class missing.
- **Vibe**: most are stubs; no base class; inline `if` checks; results not persisted.

---

## Pillar 2 — Checkpoints

### Requirement

Checkpoints are **verification gates** that examine the agent's output **after** it is generated. They detect hallucinations (fabricated commit SHAs, file paths that don't exist), schema violations (missing required fields), and semantic incoherence (the cited code snippet doesn't actually appear at the cited line range). Checkpoints must be capable of triggering a retry or escalation when they fail.

The original plan listed **8 checkpoints**:

1. `commit_exists` — every cited SHA resolves via `git cat-file`
2. `path_exists` — every cited file path exists at the cited SHA
3. `code_snippet_exists` — the cited snippet actually appears in that file at that SHA
4. `line_range_valid` — start/end lines are within the file's bounds at that SHA
5. `branch_exists` — every cited branch is a real ref
6. `symptom_explanation_present` — the bug location includes a non-empty symptom_explanation
7. `confidence_in_range` — confidence ∈ [0, 1]
8. `bug_type_in_enum` — bug_type is one of {`introduced`, `removed`, `commented_out`, `legacy`}

**Stretch (reliable-tool marker, not vibe-disqualifying if absent):**

9. `introduction_verified` — when `bug_type == "introduced"`, the harness deterministically confirms the cited code snippet is absent from the parent commit (e.g., `git show <parent>:<file>` and string match). If the pattern IS present in the parent, the agent over-claimed and a `MISLABELED_BUG_TYPE` alarm should fire. **The presence of this checkpoint moves the build from "trust the agent" to "verify the agent" on the most semantically important field, and is a strong reliable-tool indicator.**

### Files that must exist

- `harness/checkpoints/` directory
- A `base.py` defining the abstract `Checkpoint`
- Concrete implementations (e.g., `reference.py` for git references, `semantic.py` for content checks)

### Verification commands

```bash
ls -la harness/checkpoints/
rg "class.*Checkpoint" harness/checkpoints/
rg -n "checkpoint" harness/loop.py
rg -n "verify\|evaluate" harness/checkpoints/

# Look for where checkpoints are run against agent output
rg -B 2 -A 5 "checkpoint" harness/loop.py | head -60

# Confirm checkpoint failures raise alarms (not just log)
rg -n "alarm\|raise_alarm" harness/checkpoints/
```

### Specific behavioral checks

1. **Each checkpoint is run against actual agent output** (not against synthetic test data). Trace the path from `agent.locate_bug(...)` return value into `verify_checkpoints(...)` or equivalent.

2. **Checkpoint results are persisted in state**. Open `state.py` and look for `checkpoint_history` (or similar). Each entry should record name, pass/fail, the stage it ran in, and a detail string when it failed.

3. **Failed checkpoints trigger an alarm and a retry**. Check the loop logic — when `commit_exists` fails for SHA `00000000`, what happens? It must (a) raise a `HALLUCINATED_REF` alarm and (b) prompt the agent to retry with feedback. Silent passthrough is a vibe pattern.

4. **The retry has a bound** — the loop must not infinitely retry. There should be a `max_retries` or equivalent.

5. **`code_snippet_exists` does real string matching against `git show`**, not just a "looks plausible" LLM call. The point of this checkpoint is to be deterministic. If it itself calls an LLM, the verification is circular.

6. **`line_range_valid` actually reads the file at the SHA** to confirm the line count. Look for `git show <sha>:<path>` in its implementation.

7. **`confidence_in_range` and `bug_type_in_enum` are not optional** — they should always be applied, since they are cheap.

8. **Checkpoint base class is present** and concrete checkpoints inherit from it.

### Vibe red flags

- Validation done inline in `loop.py` with `if not result.sha: raise ...`
- Checkpoints exist but are never called against actual agent output
- A single `validate_response()` function with hardcoded checks
- Checkpoint that asks an LLM "is this code plausible?" — circular verification
- No retry pathway when a checkpoint fails
- Checkpoint failures silently logged without raising alarms

### Reliable markers

- One concrete checkpoint class per check
- `Checkpoint` base class with `verify(state, agent_output) -> CheckpointResult`
- Results persisted with stage attribution
- Failure → alarm raised + retry triggered (bounded)
- Deterministic verification (git/file/regex), not LLM-based
- All 8 listed checkpoints implemented

### Verdict criteria

- **Reliable**: 6+ of the 8 implemented and actually invoked; failures raise alarms; retries are bounded; base class exists.
- **Mixed**: 3–5 implemented OR retry logic is hand-wavy OR some checks are LLM-based.
- **Vibe**: inline validation; no separate module; no retry on failure.

---

## Pillar 3 — Materials

### Requirement

Materials are the **persisted state** of the investigation — separate from the agent's prompt context, durable, schema-versioned, and inspectable after the run. The agent's reasoning is ephemeral; materials are the truth.

Key contents:

- `InvestigationState` with `investigation_id`, `current_stage`, `bug_report`, `candidates`, `eliminated_shas`, `alarms_raised`, `checkpoint_history`, `guardrail_history`, `tokens_used`, `spend_used`.
- Pydantic models for: `BugReport`, `SuspectCommit`, `BugLocation`, `Stage` enum.
- A store that persists state to disk at each stage transition.

### Files that must exist

- `harness/materials/state.py` — model definitions
- `harness/materials/store.py` — persistence layer (read/write to disk)
- `./investigations/{investigation_id}/` directories after a run, containing per-stage JSON snapshots

### Verification commands

```bash
ls -la harness/materials/
rg "class.*BaseModel" harness/materials/state.py
rg "model_dump\|model_dump_json" harness/materials/store.py

# Confirm state is saved after each stage
rg -n "save\|persist" harness/materials/store.py
rg -n "store\|save_state" harness/loop.py

# Look at an actual investigation directory
ls -la investigations/$(ls -t investigations/ | head -1)/

# Inspect a saved state file
cat investigations/$(ls -t investigations/ | head -1)/state_*.json | python -m json.tool | head -50
```

### Specific behavioral checks

1. **Pydantic v2 models are used** (look for `BaseModel`, `model_dump`, `model_dump_json`). Plain `@dataclass` is acceptable but Pydantic is the spec.

2. **`Stage` is a proper `Enum`** with all expected values: `intake`, `scope`, `reproduction_check`, `locate`, `done`, `exhausted_no_result`, `aborted`. Magic strings are a vibe pattern.

3. **State is persisted at every stage transition**, not only at the end. Open `investigations/<latest>/` and confirm there are multiple `state_<stage>.json` files. If there's only one file, persistence is lazy and the audit trail is incomplete.

4. **`BugLocation` has all required fields**: `file_path`, `line_start`, `line_end`, `snippet`, `bug_type`, `symptom_explanation`, `suggested_fix`. The recent Phase 4.5 work also added `call_context`.

5. **`SuspectCommit.branches` is a list** (not a single string), reflecting the multi-branch attribution model. Even with the origin-only heuristic, it should remain a list for schema stability.

6. **`bug_type` is constrained to a precise four-value enum-like set** at the model level (Pydantic `Literal` or enum): `introduced`, `removed`, `commented_out`, `legacy`. Free-form strings here are a vibe pattern. Critically, the **semantics must be enforced by the agent prompt**, not just the schema:
   - `introduced` means the buggy code did **not** exist in the parent commit. The agent must verify against parent diff.
   - `removed` means a protective guard existed in the parent and was deleted here.
   - `commented_out` means a protective guard was commented out.
   - `legacy` is the default fallback — the bug existed before this commit; this commit only relates to it.
   
   **Vibe test:** run the agent against a repo where multiple commits touch buggy code. Only ONE commit should be labeled `introduced`; the rest should be `legacy`. If all suspects come back as `introduced`, the agent is over-claiming and the prompt is not enforcing the semantics. This is theatre — the taxonomy exists but the agent ignores it.

7. **Cross-references via IDs**: alarms refer to checkpoints by name, candidates refer to commits by SHA. No raw object references that won't survive serialization.

8. **`eliminated_shas` is a `set[str]`** — order doesn't matter, duplicates are meaningless. Using a list here is a minor smell.

9. **`tokens_used` and `spend_used` are tracked**. Inspect the latest saved state. If both are `0` after a real agent run, the harness is not capturing usage data despite the guardrails claiming to enforce limits (theatre).

10. **State is loadable**: `InvestigationState.model_validate_json(open("state_done.json").read())` must work without modification. If not, the schema isn't self-contained.

### Vibe red flags

- State held only in module-level globals or `argparse` namespaces
- `dict`s passed around instead of Pydantic models
- Magic stage strings (`if stage == "locate"`) instead of an enum
- Only one state file written, at the end
- `tokens_used` and `spend_used` stay `0` despite real API calls
- Models defined inside other files (no `state.py` module)
- No `store.py` — persistence inlined wherever convenient

### Reliable markers

- Pydantic v2 BaseModel for every artifact
- `Stage` enum + `Literal` constraints for bug_type
- Snapshot saved at each stage transition into `investigations/<id>/state_<stage>.json`
- `store.py` is the single source of truth for persistence
- Token and spend counters reflect real usage from agent `_last_usage`
- Loadable, round-trippable schema

### Verdict criteria

- **Reliable**: Pydantic models, enum stages, per-stage snapshots, real token/spend tracking, loadable schema.
- **Mixed**: Pydantic exists but only one snapshot per run, or counters always zero.
- **Vibe**: dicts everywhere, no persistence module, state lost on exit.

---

## Pillar 4 — Alarms

### Requirement

Alarms are **typed, severity-bearing anomaly signals** raised when the harness catches something suspect — usually a checkpoint failure or guardrail violation. Alarms have a well-defined taxonomy (an enum of alarm types), structured payloads, and a recommended action (e.g., `retry stage`, `abort investigation`, `request human review`). Alarms are persisted into materials and emitted as OTel span events.

The original plan listed **13 alarm types** in the taxonomy, including at minimum:

- `HALLUCINATED_REF` — agent cited a non-existent SHA/branch/path
- `HALLUCINATED_CODE` — agent cited code that isn't at the location it claims
- `SCHEMA_VIOLATION` — agent output failed to parse
- `LOW_CONFIDENCE_RESULT` — agent produced output but with confidence below threshold
- `BUDGET_EXCEEDED` — a resource guardrail tripped
- `MISSING_SYMPTOM_LINK` — no plausible chain from suspect commit to symptom
- `RE_PROPOSED_ELIMINATED` — agent re-suggested a SHA the user already eliminated
- `STAGE_TIMEOUT` — a stage took longer than allowed
- `READ_ONLY_VIOLATION` — a write operation was attempted (must never fire in this build but should exist)
- And others (`FOCUS_DRIFT`, `RETRY_EXHAUSTED`, `MALFORMED_AGENT_OUTPUT`, `CONTEXT_OVERFLOW`)

### Files that must exist

- `harness/alarms/types.py` — `AlarmType` enum + `Severity` enum + alarm Pydantic model
- `harness/alarms/bus.py` — the `AlarmBus` that emits alarms (persist + OTel + log)

### Verification commands

```bash
ls -la harness/alarms/
rg "class.*AlarmType\|class.*Severity" harness/alarms/
rg "raise_alarm\|emit" harness/alarms/

# Count alarm types defined
rg "^\s*[A-Z_]+\s*=" harness/alarms/types.py | wc -l

# Confirm alarms are raised from checkpoints and guardrails
rg -n "raise_alarm\|alarm_bus" harness/checkpoints/ harness/guardrails/

# Look at a real run's alarms
cat investigations/$(ls -t investigations/ | head -1)/state_locate.json | python -c "import json,sys; print(json.dumps(json.load(sys.stdin)['alarms'], indent=2))" 2>/dev/null
```

### Specific behavioral checks

1. **`AlarmType` is an `Enum`** with all listed types. Free-form strings are a vibe pattern.

2. **`Severity` is an `Enum`** with at least `low`/`medium`/`high`/`critical`. Each alarm has a severity attached.

3. **Each alarm has a `recommended_action`** — a string describing what the harness should do (`retry stage`, `abort`, `request human review`, etc.). Without this, alarms are just decorated print statements.

4. **Alarms are persisted into `state.alarms_raised`** with full context: type, severity, action, stage, and a free-form `ctx` dict for variable details.

5. **Alarms appear as OTel span events**, attached to the stage span where they were raised. Look in `harness/telemetry/tracer.py` and any place that creates spans to confirm `add_event("alarm.<type>", attributes={...})` is being called.

6. **The dog-voice friendly message is separate from the structured payload**. The casual `"Hold up dog — the agent made up a commit hash"` is a print/UI concern, not the canonical record.

7. **Alarms raised during retries are also persisted** — the audit trail must show every retry attempt's failures, not just the final attempt's.

8. **`RE_PROPOSED_ELIMINATED` exists in the enum** even if it isn't actively fired (the recent work flagged this as wired-but-not-firing). If it's documented as deferred, that's fine; if it's silently missing, that's a gap.

9. **An alarm count is exposed** in the final state (`state.alarms_raised` length), used by the Streamlit pillar panel and final summary.

### Vibe red flags

- Alarms are just `print("WARNING: ...")` calls
- No enum — alarm types are arbitrary strings
- No severity field
- No `recommended_action`
- Alarms not persisted in state — only the count is tracked
- Alarms not emitted as OTel events
- Dog-voice messages mixed into the canonical alarm payload

### Reliable markers

- `AlarmType` and `Severity` are proper Enums
- Alarms are Pydantic models with full context
- `AlarmBus` is the single emission point; it persists, traces, and logs
- All ~13 alarm types exist; stub types are documented
- Alarms tied to the OTel span of the stage that raised them
- Friendly UI strings are derived from the structured payload, not stored in it

### Verdict criteria

- **Reliable**: typed taxonomy, severity, action, persisted, OTel events, at least 10 of 13 types.
- **Mixed**: enum exists but no severity OR not persisted in state OR no OTel events.
- **Vibe**: print statements, no taxonomy, alarms lost after the stage finishes.

---

## Cross-Cutting Requirements

### CC-1 — Multi-turn loop

The harness must support **multiple agent invocations against the same investigation state**, with eliminated branches and prior alarms carried forward.

Verification:

```bash
# Look for explicit turn/loop concept in the Streamlit app
rg -n "turns\|session_state.turns" app/streamlit_app.py

# Confirm eliminated_branches accumulates across turns
rg -n "eliminated_branches\|eliminated_shas" app/streamlit_app.py harness/loop.py

# Confirm the harness can be re-invoked with prior state
rg -B 2 -A 5 "def run" harness/loop.py
```

Checks:

1. The Streamlit UI maintains a list of turns in `st.session_state.turns`, each carrying the resulting state.
2. Eliminated branches from prior turns are passed into subsequent turns.
3. Each turn produces a new `investigation_id` OR the same id with stage progression (either model is acceptable; consistency matters).
4. The CLI can run a single turn; the UI can run multiple — same harness function underneath.

**Vibe red flag:** the "loop" is the same single-shot harness call wrapped in a button. No state carries forward.

### CC-2 — Swappable agent

A second worker must be wired in via the same interface as the primary `ClaudeAgent`.

Verification:

```bash
# Find the agent interface
cat agents/base.py

# Confirm at least two concrete agents
ls agents/

# Confirm the agent is injectable at the loop level
rg -n "agent\s*:" harness/loop.py
```

Checks:

1. `agents/base.py` defines a `Protocol` or `ABC` (e.g., `Agent` with `propose_candidates`, `locate_bug` methods).
2. `agents/claude_agent.py` and at least one other agent (`grep_agent.py`, `stub_agent.py`) implement it.
3. The loop accepts an agent instance as a parameter — not hardcoded to import `ClaudeAgent`.
4. The CLI exposes an `--agent` flag (or equivalent) to choose at runtime.

**Vibe red flag:** there is a `grep_agent.py` file but it's a stub that hasn't been wired into the CLI/UI, so the "swap" is theoretical.

**Bonus question:** is the swap **demonstrably exercised**, not just theoretically possible? Run the alternate agent against the test repo and confirm the harness produces a valid (possibly less accurate) result.

### CC-3 — Telemetry / observability

The harness emits OpenTelemetry spans for the investigation as a whole, each stage, each guardrail evaluation, and each alarm event. Spans have parent/child relationships and structured attributes.

Verification:

```bash
ls harness/telemetry/
rg "tracer\|start_as_current_span" harness/

# Run a real investigation and inspect the span tree
python cli.py --repo /tmp/testrepo --bug "Player health goes negative" 2>&1 | grep -E '"name":\|"parent_id":' | head -30
```

Checks:

1. There is a top-level `loop` span.
2. Each stage (`intake`, `scope`, `reproduction_check`, `locate`) has its own span as a child of `loop`.
3. Guardrail evaluations are spans, children of the stage span where they ran.
4. Alarms are emitted as span events with attributes (`severity`, `recommended_action`, `ctx.*`).
5. Span attributes are consistent and useful (not just `"name": "stage"` with nothing else).

**Vibe red flag:** OTel is initialized but spans are all flat (no parent/child structure), or attributes are empty/missing, or spans don't carry the investigation_id.

### CC-4 — Read-only enforcement

The harness must never modify the user's git repo. This is enforced by:

1. The `READ_ONLY_REPO` guardrail (declarative claim).
2. Absence of any write-mode git commands in the codebase.

Verification:

```bash
# Search for any git commands that would modify state
rg "git checkout\|git commit\|git push\|git merge\|git rebase\|git reset\|git branch -d\|git branch -D" --type py

# Search for any subprocess.run that writes to the repo
rg "subprocess.*run.*git" agents/ harness/ | grep -v "log\|show\|cat-file\|rev-list\|rev-parse\|for-each-ref\|name-rev\|diff"
```

Checks:

1. Only read-mode git commands appear (`log`, `show`, `cat-file`, `rev-list`, `rev-parse`, `for-each-ref`, `name-rev`, `diff`).
2. No `git checkout`, `commit`, `push`, `merge`, `rebase`, `reset`, `branch -d/-D` anywhere.
3. The `clone --depth 50` in the Streamlit UI writes to `/tmp/`, not to the user's repo — verify the target directory is always `tempfile.mkdtemp()`.
4. The "Rule out branch" button in the UI affects only `session_state`, not git.

**Vibe red flag:** the `READ_ONLY_REPO` guardrail says "pass" but a write command exists somewhere in the codebase.

### CC-5 — Honest termination

When no candidate meets the confidence floor, the loop terminates in `EXHAUSTED_NO_RESULT` rather than fabricating a suspect.

Verification:

```bash
rg "exhausted_no_result\|EXHAUSTED_NO_RESULT" harness/ agents/
rg "MIN_CONFIDENCE_TO_PROPOSE\|0\.4" harness/loop.py agents/claude_agent.py

# Demonstrate it works
python cli.py --repo /tmp/testrepo --bug "Mars rover telemetry packet corruption in PNG decoder"
# Expect: Final stage: exhausted_no_result, Candidates: 0, Alarms: 0
```

Checks:

1. `Stage.EXHAUSTED_NO_RESULT` exists in the enum.
2. The agent prompt instructs return-empty-on-low-confidence ("return [] if no candidate above 0.4, do not manufacture suspects").
3. The loop applies a confidence floor filter before declaring `done`.
4. The bogus-bug end-to-end test produces `exhausted_no_result` with zero alarms (no hallucination caught because none was attempted).

**Vibe red flag:** the enum value exists but the loop never transitions into it; the agent always produces *some* candidate even when nothing fits.

### CC-6 — HARNESS.md

A markdown document describing the harness architecture must exist.

Verification:

```bash
ls -la HARNESS.md 2>/dev/null || echo "MISSING"
wc -l HARNESS.md 2>/dev/null
```

Checks:

1. File exists at the repo root.
2. Describes the four pillars and how they interact.
3. Names the specific guardrails, checkpoints, alarms.
4. Documents the agent interface.
5. Documents the multi-turn loop.

**Vibe red flag:** `HARNESS.md` is missing, or it's a one-paragraph stub that says "the harness runs guardrails and checkpoints."

---

## Code Quality Smell Tests

These are generic indicators of vibe code regardless of the rubric.

### Type discipline

- [ ] Pydantic v2 models used for all data passed between modules
- [ ] Type hints on every public function
- [ ] No `dict[str, Any]` floating between modules (specific schemas instead)
- [ ] Enums used for all categorical fields

### Error handling

- [ ] No bare `except:` clauses
- [ ] No `except Exception: pass` (silent swallow)
- [ ] Specific exception types with informative messages
- [ ] Errors recorded in materials, not just logged

### Separation of concerns

- [ ] Agent code does not import from `harness.checkpoints` or `harness.alarms` (the agent doesn't verify itself)
- [ ] Harness code does not embed agent prompts (prompts live in the agent module)
- [ ] CLI and Streamlit UI both call `harness.loop.run` (one entry point)
- [ ] No duplicated logic between CLI and UI

### Determinism

- [ ] Agent calls use `temperature=0` for ranking/structured output
- [ ] No `time.sleep` magic
- [ ] No reliance on file-system ordering (use sorted lists)

### Testability

- [ ] `tests/` directory exists
- [ ] Each pillar has at least a smoke test
- [ ] The harness can be invoked with a stub agent for deterministic testing

### Configuration

- [ ] No hardcoded magic numbers without named constants (`MIN_CONFIDENCE_TO_PROPOSE`, `SPEND_CEILING`, etc.)
- [ ] Limits live in one place, not duplicated across guardrails

### Dependency hygiene

- [ ] `requirements.txt` pins major versions (`pydantic<3,>=2.5`, etc.)
- [ ] No unused imports
- [ ] No commented-out code blocks

---

## Vibe vs Reliable — final scoring

After working through every section above, score the codebase on each dimension:

| Dimension | Vibe | Mixed | Reliable |
|---|---|---|---|
| Guardrails | Inline ifs, no module | Module exists, some stubs | Full taxonomy, real enforcement, persisted |
| Checkpoints | Ad-hoc validation | Module exists, partial coverage | Full taxonomy, retries on failure, deterministic |
| Materials | Dicts, no persistence | Models exist, partial persistence | Pydantic, per-stage snapshots, loadable |
| Alarms | Print statements | Enum exists, no severity/action | Full taxonomy, severity, OTel events, persisted |
| Multi-turn loop | Single-shot wrapped in button | Turns tracked, partial state carry | Full state continuity across turns |
| Agent swap | One agent, stub second | Two agents, swap untested | Both wired, demonstrably exchangeable |
| Telemetry | Flat spans or none | Spans exist, weak hierarchy | Tree of spans with attributes and events |
| Read-only | Claimed not enforced | Guardrail exists, write commands present | No write commands anywhere |
| Honest termination | Always returns a candidate | Enum exists, sometimes used | Confidence floor + EXHAUSTED stage, verified end-to-end |
| Documentation | Missing or stub | One-pager | Full HARNESS.md with diagrams |

**Final verdict rubric:**

- **Reliable Tool** (≥8 Reliable, ≤1 Vibe across the 10 dimensions): this is a defensible production-pattern build. The four pillars are real, separable, and inspectable. The harness would catch a misbehaving agent. Replace the LLM and the structure still holds.

- **Mixed / Demo-quality** (4–7 Reliable, ≤3 Vibe): the architecture is largely right but has gaps. Likely a strong build with rough edges; can be tightened into a reliable tool with focused fixes.

- **Vibe Code** (≤3 Reliable, or any of: no checkpoint module, no alarm taxonomy, no state persistence, no multi-turn loop): the four-pillar framing is decoration on a prompt-engineered LLM call. The "harness" is the LLM.

When producing the final verdict, the reviewer must:

1. List the specific files inspected.
2. Cite line ranges for every claim.
3. Identify the three highest-impact improvements if the verdict is anything below Reliable Tool.
4. Identify any rubric requirements that appear completely missing (gaps the author may not realize).
5. Flag any code that *appears* to satisfy a pillar but does not actually enforce anything (theatre).

---

## Appendix — Quick sanity sequence (run these in order)

```bash
cd ~/Desktop/Gauntlet/dog
source .venv/bin/activate

# Pillar 1 — Guardrails
ls harness/guardrails/
rg -c "class.*Guardrail" harness/guardrails/

# Pillar 2 — Checkpoints
ls harness/checkpoints/
rg -c "class.*Checkpoint" harness/checkpoints/

# Pillar 3 — Materials
ls harness/materials/
rg "BaseModel\|Enum" harness/materials/state.py | head -20

# Pillar 4 — Alarms
ls harness/alarms/
rg "class AlarmType\|class Severity" harness/alarms/types.py

# Multi-turn loop
rg "turns" app/streamlit_app.py | head -5

# Agent swap
ls agents/
cat agents/base.py

# Telemetry
ls harness/telemetry/

# Read-only enforcement (these should all return zero matches)
rg "git checkout\|git commit\|git push\|git merge\|git reset" --type py | grep -v test

# Honest termination
rg "EXHAUSTED_NO_RESULT\|exhausted_no_result" harness/ agents/

# HARNESS.md
ls HARNESS.md 2>/dev/null && wc -l HARNESS.md

# Real end-to-end test
python cli.py --repo /tmp/testrepo --bug "Player health goes negative when damage exceeds current HP"
python cli.py --repo /tmp/testrepo --bug "Mars rover telemetry corruption"  # must terminate exhausted_no_result

# Inspect persisted state
LATEST=$(ls -t investigations/ | head -1)
ls investigations/$LATEST/
cat investigations/$LATEST/state_locate.json | python -m json.tool | head -80
```

Every command above should produce concrete evidence — not "looks fine," but a specific file count, class count, or output line — that the reviewer can cite in the final verdict.
