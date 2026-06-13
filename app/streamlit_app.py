"""Streamlit app — Phase 4 deliverable.

A conversational front-end for the Dog investigation harness. The UI is
read-only with respect to harness internals: it builds an InvestigationState,
calls ``harness.loop.run`` directly, and renders whatever final state comes
back. It never reaches into the pillars or mutates harness data structures.

Run with:
    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile

import streamlit as st

# Make the project root importable when Streamlit launches from app/.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agents.claude_agent import ClaudeAgent  # noqa: E402
from harness.loop import run  # noqa: E402
from harness.materials.state import (  # noqa: E402
    BugReport,
    InvestigationState,
    Stage,
)

LOOKBACK_DAYS = 30

st.set_page_config(page_title="Branch Sniffer", page_icon="🐕", layout="wide")


# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #
def _init_state() -> None:
    st.session_state.setdefault("repo_path", None)
    st.session_state.setdefault("repo_label", "")
    st.session_state.setdefault("turns", [])
    st.session_state.setdefault("eliminated_branches", set())
    st.session_state.setdefault("stack_trace", "")
    st.session_state.setdefault("description", "")
    st.session_state.setdefault("refinements", [])
    st.session_state.setdefault("rejected_notes", [])


def _reset_investigation() -> None:
    """Wipe everything tied to a particular repo so a new repo starts clean."""
    st.session_state.turns = []
    st.session_state.eliminated_branches = set()
    st.session_state.stack_trace = ""
    st.session_state.description = ""
    st.session_state.refinements = []
    st.session_state.rejected_notes = []


def _set_repo(path: str, label: str) -> None:
    if st.session_state.repo_path != path:
        _reset_investigation()
    st.session_state.repo_path = path
    st.session_state.repo_label = label


# --------------------------------------------------------------------------- #
# Git / harness helpers
# --------------------------------------------------------------------------- #
def _is_git_repo(path: str) -> bool:
    return os.path.isdir(path) and os.path.isdir(os.path.join(path, ".git"))


def _find_git_root(start: str) -> str | None:
    """Walk a directory tree and return the parent of the first .git dir found."""
    for root, dirs, _ in os.walk(start):
        if ".git" in dirs:
            return root
    return None


def _branch_shas(repo_path: str, branches: set[str]) -> set[str]:
    """Resolve eliminated branches to the full set of commits reachable on them.

    Mirrors cli.py: ``git rev-list <branch> --since`` gives every commit on the
    branch within the lookback window.
    """
    shas: set[str] = set()
    for branch in branches:
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "rev-list", branch,
                 f"--since={LOOKBACK_DAYS} days ago"],
                capture_output=True, text=True, check=True,
            )
        except subprocess.CalledProcessError:
            continue
        shas.update(s.strip() for s in result.stdout.split("\n") if s.strip())
    return shas


def _effective_description() -> str:
    parts = [st.session_state.description]
    parts += [f"Follow-up clarification: {r}" for r in st.session_state.refinements]
    parts += st.session_state.rejected_notes
    return "\n\n".join(p for p in parts if p.strip())


def _run_turn(user_input: str) -> None:
    """Build a fresh state from accumulated context, run the loop, record a turn."""
    repo_path = st.session_state.repo_path
    state = InvestigationState(
        bug_report=BugReport(
            description=_effective_description(),
            stack_trace=st.session_state.stack_trace or None,
        ),
        repo_path=repo_path,
        lookback_days=LOOKBACK_DAYS,
        focus_topic=st.session_state.description,
    )
    state.eliminated_shas = _branch_shas(repo_path, st.session_state.eliminated_branches)

    try:
        agent = ClaudeAgent()
    except Exception as exc:  # noqa: BLE001 - surface config errors in the UI
        st.error(f"Couldn't start the Claude agent: {exc}\n\n"
                 "Is ANTHROPIC_API_KEY set in your environment?")
        return

    with st.spinner("🐕 sniffing it out…"):
        try:
            final = run(state, agent)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Investigation failed: {exc}")
            return

    st.session_state.turns.append({"user_input": user_input, "state": final})
    st.rerun()


# --------------------------------------------------------------------------- #
# Sidebar: repo input + four-pillars panel
# --------------------------------------------------------------------------- #
def _sidebar_repo_input() -> None:
    st.sidebar.header("🐕 Repo")

    local_tab, github_tab, zip_tab = st.sidebar.tabs(["Local path", "GitHub URL", "Zip upload"])

    # --- Local path ---
    with local_tab:
        path = st.text_input("Absolute path to a git repo", key="local_path_input")
        if path:
            if _is_git_repo(path):
                st.success(f"✅ Valid git repo")
            elif os.path.isdir(path):
                st.error("❌ Directory exists but has no .git")
            else:
                st.error("❌ Not a directory")
        if st.button("Use this repo", key="use_local", disabled=not (path and _is_git_repo(path))):
            _set_repo(path, path)
            st.rerun()

    # --- GitHub URL ---
    with github_tab:
        url = st.text_input("https://github.com/owner/repo", key="github_url_input")
        if st.button("Clone & use", key="use_github", disabled=not url):
            with st.spinner("Cloning (depth 50)…"):
                dest = tempfile.mkdtemp(prefix="dog_clone_")
                result = subprocess.run(
                    ["git", "clone", "--depth", "50", url, dest],
                    capture_output=True, text=True,
                )
            if result.returncode == 0 and _is_git_repo(dest):
                st.success("✅ Cloned")
                _set_repo(dest, url)
                st.rerun()
            else:
                st.error(f"❌ Clone failed:\n{result.stderr.strip() or 'unknown error'}")

    # --- Zip upload ---
    with zip_tab:
        uploaded = st.file_uploader("Upload a zipped repo", type="zip", key="zip_input")
        if uploaded is not None and st.button("Unzip & use", key="use_zip"):
            with st.spinner("Unzipping…"):
                dest = tempfile.mkdtemp(prefix="dog_zip_")
                try:
                    with zipfile.ZipFile(uploaded) as zf:
                        zf.extractall(dest)
                except zipfile.BadZipFile:
                    st.error("❌ Not a valid zip file")
                    return
                root = _find_git_root(dest)
            if root is None:
                st.error("❌ No .git directory found inside the zip")
            else:
                st.success("✅ Found git repo in archive")
                _set_repo(root, f"{uploaded.name} → {os.path.relpath(root, dest)}")
                st.rerun()

    if st.session_state.repo_path:
        st.sidebar.divider()
        if st.sidebar.button("🧹 Clear repo & history", key="clear_repo"):
            st.session_state.repo_path = None
            st.session_state.repo_label = ""
            _reset_investigation()
            st.rerun()


def _sidebar_pillars() -> None:
    """Four-pillars panel — reads from the latest turn's final state."""
    st.sidebar.divider()
    st.sidebar.subheader("🛡️ Four pillars")

    if not st.session_state.turns:
        st.sidebar.caption("No investigation run yet.")
        return

    state = st.session_state.turns[-1]["state"]
    c1, c2 = st.sidebar.columns(2)
    c1.metric("Alarms raised", len(state.alarm_history))
    c2.metric("Checkpoints", len(state.checkpoint_history))
    c1.metric("API calls", f"{state.calls_made} / 20")
    c2.metric("Spend", f"${state.spend_used:.2f} / $2")

    if state.alarm_history:
        with st.sidebar.expander(f"⚠️ {len(state.alarm_history)} alarm(s)"):
            for a in state.alarm_history:
                st.markdown(f"**{a.get('type')}** · `{a.get('severity')}`")
                if a.get("context"):
                    st.caption(str(a["context"]))


def _sidebar_bug_types() -> None:
    """Always-visible rubric explaining how each bug_type is classified."""
    with st.sidebar.expander("ℹ️ Bug types"):
        st.markdown(
            "- **introduced** — the buggy code was added in this commit\n"
            "- **removed** — a fix/guard was deleted in this commit, re-exposing the bug\n"
            "- **commented_out** — protective code was commented out, disabling the safeguard\n"
            "- **legacy** — this commit relates to the bug (calls it, fails to fix it, "
            "propagates it) but the buggy code existed before this commit\n"
        )


# --------------------------------------------------------------------------- #
# Main pane: thread rendering
# --------------------------------------------------------------------------- #
def _confidence_badge(conf: float) -> str:
    if conf >= 0.7:
        color = "#1a7f37"  # green
    elif conf >= 0.4:
        color = "#bf8700"  # amber
    else:
        color = "#cf222e"  # red
    return (
        f'<span style="background:{color};color:white;padding:2px 8px;'
        f'border-radius:10px;font-weight:600;">{conf:.0%} confidence</span>'
    )


def _branch_badges(branches: list[str]) -> str:
    if not branches:
        return '<span style="color:#888;">(no branch info)</span>'
    return " ".join(
        f'<span style="background:#ddf4ff;color:#0969da;padding:1px 7px;'
        f'border-radius:8px;font-size:0.85em;margin-right:4px;">🌿 {b}</span>'
        for b in branches
    )


_STAGE_BANNER = {
    Stage.DONE: ("✅ Investigation complete", "success"),
    Stage.EXHAUSTED_NO_RESULT: ("🤷 Exhausted — no confident culprit found", "warning"),
}


def _render_stage_banner(state: InvestigationState) -> None:
    label, kind = _STAGE_BANNER.get(
        state.current_stage,
        (f"🛑 Aborted at stage: {state.current_stage.value}", "error"),
    )
    getattr(st, kind)(label)


def _render_candidate(state, commit, turn_idx: int, cand_idx: int, actionable: bool) -> None:
    with st.container(border=True):
        top = st.columns([3, 1])
        top[0].markdown(f"**`{commit.short_sha}`** — {commit.message}")
        top[1].markdown(_confidence_badge(commit.confidence), unsafe_allow_html=True)

        st.markdown(_branch_badges(commit.branches), unsafe_allow_html=True)
        st.caption(f"by {commit.author} · {commit.date:%Y-%m-%d}")
        if commit.rationale:
            st.markdown(f"_{commit.rationale}_")

        loc = commit.bug_location
        if loc is not None:
            with st.expander(f"🔬 Bug location — {loc.file_path}:{loc.line_range[0]}–{loc.line_range[1]}"):
                st.markdown(f"**Bug type:** `{loc.bug_type}`")
                if loc.code_snippet:
                    st.code(loc.code_snippet)
                if loc.call_context:
                    st.markdown(f"**When this gets called:** {loc.call_context}")
                st.markdown(f"**What's wrong:** {loc.explanation or '—'}")
                st.markdown(f"**Why it causes the symptom:** {loc.symptom_link or '—'}")

        if actionable:
            st.caption("Rules a branch out of this investigation only — doesn't touch git.")
            cols = st.columns(len(commit.branches) + 1 if commit.branches else 2)
            for i, branch in enumerate(commit.branches):
                if cols[i].button(
                    f"🚫 Rule out {branch}",
                    key=f"elim_{turn_idx}_{cand_idx}_{branch}",
                ):
                    st.session_state.eliminated_branches.add(branch)
                    _run_turn(f"Eliminate branch `{branch}` and re-investigate")
            wrong_col = cols[len(commit.branches)] if commit.branches else cols[1]
            if wrong_col.button(
                "👎 Mark wrong, re-rank",
                key=f"wrong_{turn_idx}_{cand_idx}",
            ):
                st.session_state.rejected_notes.append(
                    f"Note: commit {commit.short_sha} ({commit.message}) was reviewed by "
                    "the user and rejected as NOT the cause. Do not propose it again; "
                    "rank other candidates instead."
                )
                _run_turn(f"Mark `{commit.short_sha}` wrong and re-rank")


def _render_agent_turn(state: InvestigationState, turn_idx: int, actionable: bool) -> None:
    _render_stage_banner(state)
    if not state.candidate_commits:
        st.info("No candidate commits cleared the confidence floor for this turn.")
        return
    for cand_idx, commit in enumerate(state.candidate_commits):
        _render_candidate(state, commit, turn_idx, cand_idx, actionable)


def _render_thread() -> None:
    last = len(st.session_state.turns) - 1
    for turn_idx, turn in enumerate(st.session_state.turns):
        with st.chat_message("user"):
            st.markdown(turn["user_input"])
        with st.chat_message("assistant", avatar="🐕"):
            _render_agent_turn(turn["state"], turn_idx, actionable=(turn_idx == last))


def _render_followup() -> None:
    st.divider()
    st.subheader("➕ Add to the investigation")
    col1, col2 = st.columns(2)
    refine = col1.text_area(
        "Refine the bug description", key="followup_refine",
        placeholder="More detail about what you're seeing…", height=120,
    )
    trace = col2.text_area(
        "Add / extend a stack trace", key="followup_trace",
        placeholder="Paste a stack trace…", height=120,
    )
    if st.button("Add to investigation", type="primary", disabled=not (refine or trace)):
        label_bits = []
        if refine:
            st.session_state.refinements.append(refine)
            label_bits.append("refined the bug description")
        if trace:
            existing = st.session_state.stack_trace
            st.session_state.stack_trace = (existing + "\n" + trace).strip() if existing else trace
            label_bits.append("added a stack trace")
        _run_turn("Follow-up: " + " and ".join(label_bits))


# --------------------------------------------------------------------------- #
# Main pane: entry views
# --------------------------------------------------------------------------- #
def _render_welcome() -> None:
    st.title("🐕 Branch Sniffer")
    st.caption("Let's sniff out the commit that broke your build.")
    st.markdown(
        "**👈 Load a repo from the sidebar to get started.**\n\n"
        "Pick one of three ways to point Branch Sniffer at your code:\n"
        "- **Local path** — an absolute path to a git repo on this machine\n"
        "- **GitHub URL** — Branch Sniffer shallow-clones it for you\n"
        "- **Zip upload** — drop in a zipped repo and Branch Sniffer finds the `.git`\n"
    )


def _render_repo_loaded() -> None:
    st.title("🐕 Branch Sniffer")
    st.markdown(f"**Repo:** `{st.session_state.repo_label}`")
    st.caption(f"resolved to `{st.session_state.repo_path}`")
    st.caption("Read-only • the harness never modifies your repo or branches.")

    if not st.session_state.turns:
        st.subheader("What's the bug?")
        desc = st.text_area(
            "Describe the bug / observed symptoms",
            key="initial_bug",
            placeholder="e.g. camera flickers when the player jumps",
            height=140,
        )
        trace = st.text_area(
            "Stack trace (optional)", key="initial_trace", height=120,
            placeholder="Paste a stack trace if you have one…",
        )
        if st.button("🐕 Sniff it", type="primary", disabled=not desc.strip()):
            st.session_state.description = desc.strip()
            st.session_state.stack_trace = trace.strip()
            _run_turn(desc.strip())
    else:
        _render_thread()
        _render_followup()


# --------------------------------------------------------------------------- #
def main() -> None:
    _init_state()
    _sidebar_repo_input()
    if st.session_state.repo_path:
        _sidebar_pillars()
        _sidebar_bug_types()
        _render_repo_loaded()
    else:
        _render_welcome()


main()
