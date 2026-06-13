# 🐕 Branch Sniffer

*"Yo dog, we sniffed out the branch."*

An AI-governed harness that finds the commit on `main` that broke your build — and the specific line of code inside it. The harness owns guardrails, checkpoints, materials, alarms; the agent just does the analysis.

## Status: Phase 1 — Skeleton

The four pillars are wired, the loop runs end-to-end with stub agents, OpenTelemetry traces print to the console, and investigation state persists to JSON after every stage. **Real agent logic and the Streamlit UI come in Phases 2–6.**

## Quick start

```bash
pip install -r requirements.txt

# Run end-to-end with the stub Claude agent
python cli.py --repo /path/to/some/git/repo --bug "test description"

# Or with the deterministic grep agent
python cli.py --repo /path/to/some/git/repo --bug "test description" --agent grep
```

State for each run lands in `./investigations/{id}/state_{stage}.json`. OTel spans print to stdout.

## Architecture

```
harness/
  guardrails/    # Pillar 1: declared constraints
  checkpoints/   # Pillar 2: explicit pass/fail gates
  materials/     # Pillar 3: typed state + JSON persistence
  alarms/        # Pillar 4: structured alarm types
  telemetry/     # Cross-cutting: OpenTelemetry
  loop.py        # Orchestrates the pillars; imports only Protocols
agents/
  base.py        # Agent Protocol (the swappable interface)
  claude_agent.py
  grep_agent.py
app/
  streamlit_app.py
cli.py
```

The loop only ever calls agents through the `Agent` Protocol. To swap workers, change one line in `cli.py`.

## Where to fill in next

In rough build order:

1. **`agents/claude_agent.py`** — wire `Anthropic()` and implement `propose_candidates`. Read `git log --since=<days>.days --pretty=format:%H%x09%an%x09%ad%x09%s --name-only` and ask Claude to rank.
2. **`agents/claude_agent.py`** — implement `locate_bug`: pull `git show <sha>` and ask for a `BugLocation`. Pay attention to `bug_type` — the prompt should consider `introduced`, `removed`, and `commented_out` failure modes.
3. **`harness/loop.py`** — wire token + cost accounting from Anthropic's usage response into `state.tokens_used` / `state.spend_used`.
4. **`harness/guardrails/focus.py`** — replace the keyword stub with a real cheap-LLM classifier.
5. **`app/streamlit_app.py`** — build the branch board, alarm panel, trace view.
6. **`agents/grep_agent.py`** — implement deterministic `git log -S` search for portability bonus.

See `DOG_PRD.md` for the full 24-hour build plan.
