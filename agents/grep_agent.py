"""GrepAgent — deterministic second worker, used for the portability bonus.

Uses `git log -S <term>` against bug-report keywords. No LLM, no API key, $0 cost.
Trips DIFFERENT checkpoints than ClaudeAgent — it never hallucinates SHAs or
code, but its templated rationale will trip MISSING_SYMPTOM_LINK and it tends to
trip GAVE_UP_LOW_CONFIDENCE when keywords are too generic.

PHASE 1: this is a stub. PHASE 6: real impl.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime

from agents.base import Agent, DiffSummary
from harness.materials.state import (
    BugLocation,
    FixProposal,
    InvestigationState,
    SuspectCommit,
)


def _keywords(text: str, min_len: int = 4) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", text) if len(w) >= min_len]


# Confidence the grep agent assigns when it can tie a changed line to the bug's
# vocabulary. Deliberately modest — grep matches words, not meaning.
_GREP_MATCH_CONFIDENCE = 0.45
# Confidence when the bug's words never appear in the commit and nothing in the
# change plausibly produces the reported symptom. No evidence = no finding: a
# low number the legacy floor (MIN_LEGACY_CONFIDENCE) will drop.
_GREP_NO_EVIDENCE_CONFIDENCE = 0.15


def _changed_code_lines(repo_path: str, sha: str) -> list[str]:
    """The bodies of a commit's added/removed *code* lines, with diff markers
    stripped. Excludes git's diff metadata (``diff --git``, ``index``, ``+++``,
    ``---``, ``@@``) so a keyword can't match a file path or hunk header instead
    of real code. Empty list on any git failure — a missing diff is treated as
    no evidence, not an exception."""
    try:
        out = subprocess.run(
            ["git", "-C", repo_path, "show", "--format=", sha],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except Exception:
        return []
    lines = []
    for line in out.splitlines():
        if line[:1] not in ("+", "-"):
            continue
        if line[:3] in ("+++", "---"):  # file headers, not content
            continue
        lines.append(line[1:].strip())
    return lines


def _first_match_snippet(code_lines: list[str], terms: list[str]) -> str:
    """First changed code line containing one of the terms."""
    lowered = [t.lower() for t in terms]
    for body in code_lines:
        low = body.lower()
        if any(t in low for t in lowered):
            return body
    return ""


class GrepAgent:
    name: str = "grep"

    def __init__(self):
        pass

    def propose_candidates(self, state: InvestigationState) -> list[SuspectCommit]:
        # STUB: real impl will run git log -S <term> --since=<window>
        # for each keyword and aggregate matches.
        return []

    def locate_bug(self, state: InvestigationState, commit: SuspectCommit) -> BugLocation:
        # grep can only assert what it can see in the diff. We split the bug
        # report into two vocabularies:
        #   - the searched word(s): the description / affected-area hint
        #   - the effect context: the observed symptom(s)
        # If NEITHER appears in this commit's changes, grep has no evidence that
        # this commit produces the bug's outcome. Rather than invent a narrative
        # around a topically-adjacent change, it returns a low-confidence,
        # legacy-typed location that the harness floors will drop.
        search_terms = _keywords(state.bug_report.description)
        if state.bug_report.affected_area_hint:
            search_terms += _keywords(state.bug_report.affected_area_hint)
        effect_terms = _keywords(state.bug_report.symptoms or "")

        code_lines = _changed_code_lines(state.repo_path, commit.sha)
        low = "\n".join(code_lines).lower()
        word_found = any(t.lower() in low for t in search_terms)
        has_effect_context = any(t.lower() in low for t in effect_terms)

        file_path = commit.files_changed[0] if commit.files_changed else "?"

        if not word_found and not has_effect_context:
            return BugLocation(
                file_path=file_path,
                line_range=(1, 1),
                code_snippet="",
                bug_type="legacy",
                explanation=(
                    "grep: none of the bug's keywords appear in this commit's "
                    "changes, and nothing here matches the reported symptom — "
                    "no evidence this commit produces the bug"
                ),
                symptom_link="",  # no link to assert
                call_context="",
                confidence=_GREP_NO_EVIDENCE_CONFIDENCE,
            )

        # At least one vocabulary hit — surface the line as weak, topical
        # evidence. Still modest confidence: a word match is not a cause.
        matched = [t for t in (search_terms + effect_terms) if t.lower() in low]
        return BugLocation(
            file_path=file_path,
            line_range=(1, 1),
            code_snippet=_first_match_snippet(code_lines, matched),
            bug_type="introduced",
            explanation=f"grep: bug keyword(s) {sorted(set(matched))} appear in this commit's changes",
            symptom_link="",  # deliberately weak — trips MISSING_SYMPTOM_LINK by design
            confidence=_GREP_MATCH_CONFIDENCE,
        )

    def compare_commits(self, sha_a: str, sha_b: str, repo_path: str) -> DiffSummary:
        return DiffSummary(sha_a=sha_a, sha_b=sha_b, summary="grep stub", key_differences=[])

    def suggest_fix(self, state: InvestigationState) -> FixProposal:
        culprit = state.confirmed_culprit()
        return FixProposal(
            file_path=culprit.files_changed[0] if culprit and culprit.files_changed else "?",
            line_range=(1, 1),
            current_code="",
            proposed_change="Consider reverting this commit.",
            rationale="grep: largest change in suspected file",
            confidence=0.2,
        )

    def reply_to_user(self, state: InvestigationState, message: str) -> str:
        return "[grep agent has no conversational mode]"
