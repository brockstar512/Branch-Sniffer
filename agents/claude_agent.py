"""ClaudeAgent — primary LLM-backed worker.

PHASE 1: stub returning canned data so the loop runs end-to-end.
PHASE 2: real Anthropic SDK integration with structured output.

The real implementation will:
  - propose_candidates: read git log metadata, ask Claude to filter to suspects
  - locate_bug: pull `git show <sha>` diff, ask Claude to identify file:line:type
  - compare_commits: pull `git diff a b`, ask Claude to summarize
  - suggest_fix: based on located bug, ask Claude to propose a change
  - reply_to_user: handle conversational turns
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime

from anthropic import Anthropic

from agents.base import Agent, DiffSummary
from harness.materials.state import (
    BugLocation,
    FixProposal,
    InvestigationState,
    SuspectCommit,
)

# Sonnet pricing, per million tokens.
_SONNET_INPUT_COST_PER_TOKEN = 3.0 / 1_000_000
_SONNET_OUTPUT_COST_PER_TOKEN = 15.0 / 1_000_000

# NUL byte separates git-log fields so commit messages may contain pipes/tabs.
_NUL = "\x00"


class ClaudeAgent:
    name: str = "claude"

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-5"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.client = Anthropic(api_key=self.api_key)
        self._last_usage: dict[str, float] = {"tokens": 0, "cost": 0.0}

    def propose_candidates(self, state: InvestigationState) -> list[SuspectCommit]:
        commits = self._read_git_log(state)
        commits = self._filter_by_scope(commits, state.file_extension_scope)
        if not commits:
            self._last_usage = {"tokens": 0, "cost": 0.0}
            return []

        ranked = self._rank_with_claude(state, commits)

        by_sha = {c["sha"]: c for c in commits}
        suspects: list[SuspectCommit] = []
        for item in ranked:
            commit = by_sha.get(item.get("sha"))
            if commit is None:
                continue
            suspects.append(
                SuspectCommit(
                    sha=commit["sha"],
                    short_sha=commit["sha"][:7],
                    author=commit["author"],
                    date=commit["date"],
                    message=commit["message"],
                    files_changed=commit["files_changed"],
                    confidence=float(item.get("confidence", 0.0)),
                    rationale=item.get("rationale", ""),
                )
            )
        return suspects

    def _read_git_log(self, state: InvestigationState) -> list[dict]:
        """Run git log and parse NUL-delimited commit records with file lists."""
        result = subprocess.run(
            [
                "git",
                "-C",
                state.repo_path,
                "log",
                f"--since={state.lookback_days} days ago",
                "main",
                f"--pretty=format:%H{_NUL}%an{_NUL}%aI{_NUL}%s",
                "--name-only",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        commits: list[dict] = []
        current: dict | None = None
        for line in result.stdout.split("\n"):
            if _NUL in line:
                if current is not None:
                    commits.append(current)
                sha, author, date_str, message = line.split(_NUL, 3)
                current = {
                    "sha": sha,
                    "author": author,
                    "date": datetime.fromisoformat(date_str),
                    "message": message,
                    "files_changed": [],
                }
            elif line.strip() and current is not None:
                current["files_changed"].append(line.strip())
        if current is not None:
            commits.append(current)
        return commits

    @staticmethod
    def _filter_by_scope(commits: list[dict], scope: list[str]) -> list[dict]:
        """Keep only files whose extension is in scope; drop commits left empty."""
        filtered: list[dict] = []
        for commit in commits:
            in_scope = [
                f for f in commit["files_changed"]
                if os.path.splitext(f)[1] in scope
            ]
            if in_scope:
                filtered.append({**commit, "files_changed": in_scope})
        return filtered

    def _rank_with_claude(self, state: InvestigationState, commits: list[dict]) -> list[dict]:
        """Ask Claude to rank the most likely suspects; record token usage and cost."""
        bug = state.bug_report
        commit_payload = [
            {
                "sha": c["sha"],
                "author": c["author"],
                "date": c["date"].isoformat(),
                "message": c["message"],
                "files_changed": c["files_changed"],
            }
            for c in commits
        ]

        prompt = (
            "You are triaging which commit on the `main` branch most likely introduced "
            "a reported bug.\n\n"
            "## Bug report\n"
            f"Description: {bug.description}\n"
            f"Symptoms: {bug.symptoms or 'n/a'}\n"
            f"Affected area hint: {bug.affected_area_hint or 'n/a'}\n\n"
            "## Candidate commits (JSON)\n"
            f"{json.dumps(commit_payload, indent=2)}\n\n"
            "Identify up to 8 commits most likely related to this bug. Respond with JSON "
            "only — no prose, no markdown fences. The JSON must be a list of objects, each "
            'with exactly these keys: "sha" (the commit sha from the list above), '
            '"confidence" (a number from 0.0 to 1.0), and "rationale" (1-2 sentences '
            "explaining why this commit is suspicious). Order the list most-suspicious first."
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        self._last_usage = {
            "tokens": input_tokens + output_tokens,
            "cost": (
                input_tokens * _SONNET_INPUT_COST_PER_TOKEN
                + output_tokens * _SONNET_OUTPUT_COST_PER_TOKEN
            ),
        }

        text = next((b.text for b in response.content if b.type == "text"), "")
        return self._parse_ranking(text)

    @staticmethod
    def _parse_ranking(text: str) -> list[dict]:
        """Parse the model's JSON ranking, tolerating accidental markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            # Strip a leading ```json / ``` fence and the trailing ``` if present.
            text = text.split("\n", 1)[1] if "\n" in text else ""
            if text.rstrip().endswith("```"):
                text = text.rstrip()[: -len("```")]
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Be lenient if the model wrapped the list in an object.
            for value in data.values():
                if isinstance(value, list):
                    return value
        return []

    def locate_bug(self, state: InvestigationState, commit: SuspectCommit) -> BugLocation:
        # STUB
        return BugLocation(
            file_path=commit.files_changed[0] if commit.files_changed else "stub.cs",
            line_range=(1, 1),
            code_snippet="// stub",
            bug_type="introduced",
            explanation="stub: replace with real diff analysis",
            symptom_link="stub: replace with real causal explanation linking code to symptom",
            confidence=0.5,
        )

    def compare_commits(self, sha_a: str, sha_b: str, repo_path: str) -> DiffSummary:
        return DiffSummary(
            sha_a=sha_a,
            sha_b=sha_b,
            summary="stub comparison",
            key_differences=["stub"],
        )

    def suggest_fix(self, state: InvestigationState) -> FixProposal:
        culprit = state.confirmed_culprit()
        return FixProposal(
            file_path=culprit.files_changed[0] if culprit and culprit.files_changed else "stub.cs",
            line_range=(1, 1),
            current_code="// stub",
            proposed_change="// stub fix",
            rationale="stub: replace with real fix proposal",
            confidence=0.5,
        )

    def reply_to_user(self, state: InvestigationState, message: str) -> str:
        return "[stub] reply"
