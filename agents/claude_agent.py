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

# Literal delimiter separating git-log fields, distinctive enough not to collide
# with commit-message content.
_FIELD_SEP = "|||DOG|||"


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
                    branches=commit.get("branches", []),
                    confidence=float(item.get("confidence", 0.0)),
                    rationale=item.get("rationale", ""),
                )
            )
        return suspects

    def _read_git_log(self, state: InvestigationState) -> list[dict]:
        """Scan the most-recently-active branches, dedup by SHA, drop eliminated commits.

        Each returned commit dict carries a single-element "branches" list naming
        its *origin* branch — the branch whose tip the SHA is closest to (fewest
        commits between the SHA and that branch's tip). Ties are broken in favour
        of the branch that ``for-each-ref`` lists first. The schema stays
        ``list[str]`` so existing state files keep loading.
        """
        recent = self._recent_branches(state.repo_path)
        by_sha: dict[str, dict] = {}
        for branch in recent:
            for commit in self._log_branch(state.repo_path, branch, state.lookback_days):
                sha = commit["sha"]
                existing = by_sha.get(sha)
                if existing is None:
                    commit["branches"] = {branch}
                    by_sha[sha] = commit
                else:
                    existing["branches"].add(branch)

        commits: list[dict] = []
        for sha, commit in by_sha.items():
            if sha in state.eliminated_shas:
                continue
            origin = self._origin_branch(state.repo_path, sha, commit["branches"], recent)
            commit["branches"] = [origin] if origin else []
            commits.append(commit)
        return commits

    def _origin_branch(
        self, repo_path: str, sha: str, containing: set[str], order: list[str]
    ) -> str | None:
        """Pick the branch the SHA is closest to the tip of.

        Iterate the containing branches in ``for-each-ref`` order so that ties
        (equal distance to tip) resolve to the first-listed branch.
        """
        best: str | None = None
        best_count: int | None = None
        for branch in order:
            if branch not in containing:
                continue
            count = self._distance_to_tip(repo_path, sha, branch)
            if best_count is None or count < best_count:
                best, best_count = branch, count
        return best

    def _distance_to_tip(self, repo_path: str, sha: str, branch: str) -> int:
        """Number of commits between ``sha`` and ``branch``'s tip (``sha..branch``)."""
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-list", "--count", f"{sha}..{branch}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return int(result.stdout.strip() or "0")

    def _recent_branches(self, repo_path: str) -> list[str]:
        """Up to 10 most-recently-active local branches, newest first."""
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_path,
                "for-each-ref",
                "--sort=-committerdate",
                "--count=10",
                "refs/heads/",
                "--format=%(refname:short)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return [line.strip() for line in result.stdout.split("\n") if line.strip()]

    def _log_branch(self, repo_path: str, branch: str, lookback_days: int) -> list[dict]:
        """Run git log for one branch and parse delimited commit records with file lists."""
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_path,
                "log",
                f"--since={lookback_days} days ago",
                branch,
                f"--pretty=format:%H{_FIELD_SEP}%an{_FIELD_SEP}%aI{_FIELD_SEP}%s",
                "--name-only",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        commits: list[dict] = []
        current: dict | None = None
        for line in result.stdout.split("\n"):
            if _FIELD_SEP in line:
                if current is not None:
                    commits.append(current)
                sha, author, date_str, message = line.split(_FIELD_SEP, 3)
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
                "branches": c.get("branches", []),
            }
            for c in commits
        ]

        stack_trace_section = (
            f"## Stack trace\n{bug.stack_trace}\n\n" if bug.stack_trace else ""
        )

        prompt = (
            "You are triaging which commit most likely introduced a reported bug.\n\n"
            "## Bug report\n"
            f"Description: {bug.description}\n"
            f"Symptoms: {bug.symptoms or 'n/a'}\n"
            f"Affected area hint: {bug.affected_area_hint or 'n/a'}\n\n"
            f"{stack_trace_section}"
            "## Candidate commits (JSON)\n"
            "Each commit lists the branches it lives on in its `branches` field.\n"
            f"{json.dumps(commit_payload, indent=2)}\n\n"
            "If a stack trace is provided, use it to identify the implicated files and "
            "lines, then reason about which branch's changes most plausibly cause the "
            "reported symptom.\n\n"
            "Identify up to 8 commits most likely related to this bug. Respond with JSON "
            "only — no prose, no markdown fences. The JSON must be a list of objects, each "
            'with exactly these keys: "sha" (the commit sha from the list above), '
            '"confidence" (a number from 0.0 to 1.0), and "rationale" (1-2 sentences '
            "explaining why this commit is suspicious). Order the list most-suspicious first.\n\n"
            "If no candidate is plausibly above 0.4 confidence, return an empty list []. "
            "Do not manufacture suspects."
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        self._record_usage(response)

        text = next((b.text for b in response.content if b.type == "text"), "")
        return self._parse_ranking(text)

    def _record_usage(self, response) -> None:
        """Store token count and Sonnet-priced cost for the most recent API call."""
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        self._last_usage = {
            "tokens": input_tokens + output_tokens,
            "cost": (
                input_tokens * _SONNET_INPUT_COST_PER_TOKEN
                + output_tokens * _SONNET_OUTPUT_COST_PER_TOKEN
            ),
        }

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Drop a leading ```json / ``` fence and trailing ``` if the model added them."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
            if text.rstrip().endswith("```"):
                text = text.rstrip()[: -len("```")]
        return text

    @classmethod
    def _parse_ranking(cls, text: str) -> list[dict]:
        """Parse the model's JSON ranking, tolerating accidental markdown fences."""
        try:
            data = json.loads(cls._strip_code_fences(text))
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
        diff = self._show_commit(state.repo_path, commit.sha)
        located = self._locate_with_claude(state, commit, diff)
        return self._build_bug_location(located, commit)

    def _show_commit(self, repo_path: str, sha: str) -> str:
        """Return the full diff for a commit via `git show <sha>`."""
        result = subprocess.run(
            ["git", "-C", repo_path, "show", sha],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def _locate_with_claude(
        self, state: InvestigationState, commit: SuspectCommit, diff: str
    ) -> dict:
        """Ask Claude to pinpoint the bug within a commit's diff; record usage."""
        bug = state.bug_report
        scope = ", ".join(commit.files_changed) or "n/a"

        prompt = (
            "You are pinpointing the exact bug a suspect commit introduced. You are given "
            "the bug report and the commit's diff (`git show`).\n\n"
            "## Bug report\n"
            f"Description: {bug.description}\n"
            f"Symptoms: {bug.symptoms or 'n/a'}\n"
            f"Affected area hint: {bug.affected_area_hint or 'n/a'}\n\n"
            "## Suspect commit\n"
            f"sha: {commit.sha}\n"
            f"message: {commit.message}\n"
            f"in-scope files changed: {scope}\n\n"
            "## Diff\n"
            f"{diff}\n\n"
            "Identify the single most likely location of the bug. Classify this commit's "
            "relationship to the bug using exactly one of these `bug_type` values:\n"
            '  - "introduced": the buggy code did NOT exist in the parent commit. You must '
            "verify this by comparing this commit's diff to its parent. If you cannot confirm "
            "the buggy pattern is absent from the parent, do NOT use this label.\n"
            '  - "removed": a protective check, guard, or bounds-test existed in the parent '
            "commit and was deleted in this commit, re-exposing a previously-handled bug.\n"
            '  - "commented_out": a protective check existed in the parent and was commented '
            "out here.\n"
            '  - "legacy": the buggy code already existed before this commit. This commit '
            "touches related code — calls into the buggy method, attempts an incomplete fix, "
            "propagates the value, etc. — but did NOT introduce, remove, or comment out the "
            "cause.\n\n"
            "Default to \"legacy\" when you are not confident the bug was actually introduced/"
            "removed/commented out in this exact commit. \"introduced\" is the strongest claim; "
            "reserve it for the genuine origin.\n\n"
            "## What `confidence` means\n"
            "`confidence` is your probability that THIS commit is the actual root cause of the "
            "reported symptom — NOT your confidence that you identified a related or "
            "plausible-looking code path. These are different. If the code in this commit does "
            "not itself plausibly produce the reported symptom, confidence MUST be at most 0.3, "
            "even when you classify it as \"legacy\" and even if the commit is topically related "
            "to the bug. Do not report high confidence for a \"legacy\" classification unless you "
            "can point to the specific buggy mechanism in this commit's code.\n\n"
            "The reported symptom may not exist in this codebase at all. If nothing in this "
            "commit's code plausibly produces it, say so plainly in `explanation` and assign a "
            "low confidence — do NOT rationalize a connection or speculate that the cause lives "
            "in code you cannot see.\n\n"
            "Respond with JSON only — no prose, no markdown fences — an object with exactly "
            "these keys:\n"
            '  "file_path" (string, the file containing the bug),\n'
            '  "line_range" (a two-element array [start, end] of line numbers in the new '
            "file; for a removal, the lines surrounding the deletion),\n"
            '  "code_snippet" (string, the relevant lines of code),\n'
            '  "bug_type" (one of "introduced", "removed", "commented_out", "legacy"),\n'
            '  "explanation" (string, what is wrong with the code),\n'
            '  "symptom_link" (string, how this code causes the reported symptom),\n'
            '  "call_context" (string, a short paragraph (2-4 sentences) describing when '
            "this code path is typically invoked at runtime and what specific input values, "
            "state conditions, or call sequences could cause the bug to manifest (e.g., "
            "'TakeDamage is called from Enemy.Attack and other damage sources; the bug "
            "manifests whenever the damage parameter is greater than the current health "
            "value, which happens during overkill scenarios')),\n"
            '  "confidence" (number from 0.0 to 1.0 — your probability that THIS commit is the '
            "root cause of the symptom, per the rule above; at most 0.3 if this commit's code "
            "does not itself plausibly produce the symptom)."
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        self._record_usage(response)

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(self._strip_code_fences(text))
        except (json.JSONDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _build_bug_location(located: dict, commit: SuspectCommit) -> BugLocation:
        """Coerce the model's JSON into a validated BugLocation, with safe fallbacks."""
        line_range = located.get("line_range") or [0, 0]
        if not (isinstance(line_range, (list, tuple)) and len(line_range) == 2):
            line_range = [0, 0]

        bug_type = located.get("bug_type")
        if bug_type not in ("introduced", "removed", "commented_out", "legacy"):
            # Default to the weakest claim when the model gives nothing usable.
            bug_type = "legacy"

        return BugLocation(
            file_path=located.get("file_path")
            or (commit.files_changed[0] if commit.files_changed else "unknown"),
            line_range=(int(line_range[0]), int(line_range[1])),
            code_snippet=located.get("code_snippet", ""),
            bug_type=bug_type,
            explanation=located.get("explanation", ""),
            symptom_link=located.get("symptom_link", ""),
            call_context=located.get("call_context", ""),
            confidence=float(located.get("confidence", 0.0)),
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
