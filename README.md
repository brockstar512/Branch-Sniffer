# Bug Investigation Harness — Planning Document

## Problem
Bugs on `main` rarely come with a pointer to the commit that introduced them. Engineers spend hours bisecting and reading diffs. This harness governs an AI agent that systematically narrows down which commit on `main` most likely introduced a given bug. The harness — not the agent — owns correctness, focus, and safety.

## Domain & Demo Input
The harness operates on a local git repository. Because all work is on local git, the harness is host-agnostic (GitHub, GitLab, Stash all resolve to the same `.git` directory). At demo time the engineer enters a local repo path (drag-drop where supported, text input as the reliable fallback), selects a lookback window (**default 30 days, dropdown for 90**), and submits a real bug report from their own work.

**Demo bug:** _TO BE FILLED IN — needs repo path, bug description, and known culprit commit for ground-truth comparison._

## Architecture: Four Pillars, Demonstrably Separate

```
harness/
  guardrails/    # declared constraints, evaluated BEFORE agent acts
  checkpoints/   # explicit pass/fail gates, evaluated AFTER agent acts
  materials/     # typed I/O schemas + persisted investigation state
  alarms/        # structured alarm types: name, severity, recommended action
  loop.py        # orchestrates pillars; calls agent through fixed interface
agents/
  claude_agent.py    # primary worker (LLM-backed)
  grep_agent.py      # second worker for portability bonus (deterministic)
app/
  streamlit_app.py   # UI, visualization board, deployment target
```

The loop file is short and boring by design: load state → run guardrails → call agent → run checkpoints → raise alarms → persist → repeat. Pillar logic never lives in the agent or the loop.

## The Loop (LangGraph)
1. **Intake** — bug report + repo path + lookback window (30/90 days)
2. **Scope** — identify candidate commits on `main` within the window that touched code regions referenced by the bug
3. **Reproduction check** — non-halting checkpoint; outcome caps downstream confidence
4. **Rank** — agent proposes ranked suspect commits with rationale and per-commit confidence. If confidence stays below threshold across `GIVE_UP_THRESHOLD` consecutive attempts, harness halts and returns a structured "cannot locate" with the trace of what was tried.
5. **Inspect** — user examines a branch/commit; user observations ("not the cause", "this looks related") feed back into state; agent re-ranks
6. **Diff summarize** — on demand, agent summarizes the diff between any two commits or branches
7. **Confirm culprit** — confirmed commit is bolded + underlined on the visualization board; ruled-out commits are struck through
8. **Suggest fix** — agent proposes a structured fix (never applies it); always escalates to human

## Agent Interface (Swappable)
```python
class Agent(Protocol):
    def propose_suspects(self, state: InvestigationState) -> list[SuspectCommit]: ...
    def summarize_diff(self, a: str, b: str, repo: Repo) -> DiffSummary: ...
    def suggest_fix(self, state: InvestigationState) -> FixProposal: ...
```
Harness never imports model SDKs. Swapping agents is a one-line config change.

## Guardrails (Declared)
**Resource limits — primary control surface.** Enforced before every agent call; tripping any of them halts the loop and emits a structured "inconclusive" result rather than letting the agent spin.

| Name | Rule | Default |
|---|---|---|
| `CALL_LIMIT` | max agent calls per investigation | 20 |
| `RETRY_LIMIT` | max retries per stage before giving up on that stage | 3 |
| `TOKEN_BUDGET` | max total tokens per investigation | 200,000 |
| `SPEND_CEILING` | max dollar cost per investigation | $2.00 |
| `TIMEOUT_PER_STAGE` | max wall-clock seconds for any single stage | 60s |
| `GIVE_UP_THRESHOLD` | consecutive low-confidence proposals before harness halts with "cannot locate" | 3 |

**Safety constraints — non-negotiable.** These are not tunable; they exist to prevent the agent from doing damage regardless of resource budget.

| Name | Rule |
|---|---|
| `READ_ONLY_REPO` | no write, checkout, or apply operations |
| `NO_AUTO_APPLY` | fix proposals are never executed by the harness |
| `WINDOW_BOUND` | only commits within 30 (default) or 90 days of HEAD on `main` |
| `FOCUS_LOCK` | off-topic user messages intercepted; user confirms priority before agent sees them |

## Checkpoints (Explicit Pass/Fail)
| Name | Pass criterion |
|---|---|
| `commit_exists` | every cited SHA resolves in the repo |
| `path_exists` | every cited file path exists at that commit |
| `diff_nonempty` | diff summaries reference real hunks in the diff |
| `fix_touches_culprit` | proposed fix touches a file modified by the suspected commit |
| `reproduction_recorded` | gating, non-halting; caps downstream confidence at 0.5 if not reproduced |

## Alarms (Structured)
Each alarm: `{type, severity, context, recommended_action}`

| Type | Severity | Action |
|---|---|---|
| `CALL_LIMIT_REACHED` | high | halt + return inconclusive result |
| `TOKEN_BUDGET_EXCEEDED` | high | halt + return inconclusive result |
| `SPEND_CEILING_REACHED` | high | halt + escalate to user |
| `STAGE_TIMEOUT` | high | retry once, then halt that stage |
| `GAVE_UP_LOW_CONFIDENCE` | med | return structured "cannot locate" with trace of what was tried |
| `HALLUCINATED_REF` | high | retry stage |
| `OFF_TOPIC_DRIFT` | low | confirm priority with user |
| `LOW_CONFIDENCE_NO_REPRO` | med | recommend reproduction |
| `SCOPE_VIOLATION` | high | halt + escalate |
| `AMBIGUOUS_FIX` | med | escalate to user choice |
| `UNVERIFIED_FIX` | high | block presentation |

## Material Handling
A single Pydantic `InvestigationState` holds: bug report, repo path, window, candidate commits (each with status `unexamined` / `ruled_out` / `culprit`, confidence, rationale), checkpoint history, alarm history, focus topic, fix proposal. Persisted to JSON after every loop iteration. Replay from any stage = load JSON, resume from that node in the LangGraph.

## Human-in-the-Loop Escalations
- Off-topic message → confirm priority shift
- No reproduction recorded → confirm continue with capped confidence
- Multiple plausible culprits (no clear leader) → user picks
- Any fix proposal → user reviews before further action
- Any high-severity alarm → halt and surface to user

## Visualization (Streamlit)
- Ordered list of candidate commits with status icons
- Strikethrough on ruled-out commits
- **Bold + underline** on confirmed culprit
- Live alarm panel with severity colors
- Diff summary view for any pair of commits/branches
- Lookback window dropdown (30 / 90 days)
- Repo path input

## Tech Stack
LangGraph (loop, state, checkpoint persistence) · Streamlit (UI + deployment) · Pydantic (schemas) · Anthropic SDK (primary agent) · `git` CLI via subprocess (host-agnostic) · optional GitHub/GitLab/Stash adapters as stretch

## Portability Bonus
Demo swaps `ClaudeAgent` → `GrepAgent` (deterministic baseline using `git log -S` against bug terms) mid-session. Same harness, same checkpoints fire, same alarms route — only the worker changes.
