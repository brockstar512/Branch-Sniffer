"""Reference-validation checkpoints.

These catch the agent's most common failure mode: citing things that don't exist.
- commit_exists: cited SHA resolves
- path_exists: cited file path exists at that commit
- code_snippet_exists: cited code actually appears (type-aware!)
- line_range_valid: cited line range fits the file
- diff_nonempty: diff summaries reference real hunks
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any

from harness.checkpoints.base import CheckpointResult
from harness.materials.state import BugLocation, InvestigationState, SuspectCommit


def _git(repo_path: str, *args: str) -> str:
    """Run a git command in the given repo and return stdout. Empty string on error."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return ""
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


@dataclass
class CommitExists:
    name: str = "commit_exists"

    def evaluate(self, state: InvestigationState, output: list[SuspectCommit]) -> CheckpointResult:
        bad = []
        for c in output:
            resolved = _git(state.repo_path, "cat-file", "-t", c.sha).strip()
            if resolved != "commit":
                bad.append(c.sha[:8])
        return CheckpointResult(
            name=self.name,
            passed=not bad,
            explanation=f"unresolved SHAs: {bad}" if bad else "all SHAs resolve",
        )


@dataclass
class PathExists:
    name: str = "path_exists"

    def evaluate(self, state: InvestigationState, output: list[SuspectCommit]) -> CheckpointResult:
        bad = []
        for c in output:
            for p in c.files_changed:
                # `git ls-tree <sha> <path>` returns empty if path missing at that commit
                listing = _git(state.repo_path, "ls-tree", c.sha, "--", p).strip()
                if not listing:
                    bad.append(f"{c.short_sha}:{p}")
        return CheckpointResult(
            name=self.name,
            passed=not bad,
            explanation=f"missing paths: {bad}" if bad else "all paths exist at their commit",
        )


@dataclass
class CodeSnippetExists:
    """Type-aware. Different verification per bug_type."""
    name: str = "code_snippet_exists"

    @staticmethod
    def _normalize(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    def evaluate(self, state: InvestigationState, output: BugLocation | SuspectCommit) -> CheckpointResult:
        # Accept either a BugLocation directly or a SuspectCommit with one attached
        if isinstance(output, SuspectCommit):
            if output.bug_location is None:
                return CheckpointResult(name=self.name, passed=True, explanation="no bug_location to verify")
            loc = output.bug_location
            commit = output
        else:
            return CheckpointResult(name=self.name, passed=False, explanation="output type not supported")

        snippet_norm = self._normalize(loc.code_snippet)
        if not snippet_norm:
            return CheckpointResult(name=self.name, passed=False, explanation="empty snippet")

        if loc.bug_type == "introduced":
            # Snippet must appear in file at this commit
            file_at = _git(state.repo_path, "show", f"{commit.sha}:{loc.file_path}")
            ok = snippet_norm in self._normalize(file_at)
            return CheckpointResult(name=self.name, passed=ok, explanation=f"introduced; snippet {'found' if ok else 'NOT found'} at {commit.short_sha}:{loc.file_path}")

        if loc.bug_type == "removed":
            # Snippet must appear in parent file but NOT in this commit's file
            file_parent = _git(state.repo_path, "show", f"{commit.sha}^:{loc.file_path}")
            file_now = _git(state.repo_path, "show", f"{commit.sha}:{loc.file_path}")
            in_parent = snippet_norm in self._normalize(file_parent)
            in_now = snippet_norm in self._normalize(file_now)
            ok = in_parent and not in_now
            return CheckpointResult(
                name=self.name,
                passed=ok,
                explanation=f"removed; in_parent={in_parent}, in_now={in_now}",
            )

        if loc.bug_type == "commented_out":
            # Snippet must appear at this commit as comment lines
            file_at = _git(state.repo_path, "show", f"{commit.sha}:{loc.file_path}")
            ok = False
            for line in file_at.splitlines():
                stripped = line.lstrip()
                is_comment = stripped.startswith(("//", "#", "/*", "*"))
                if is_comment and snippet_norm in self._normalize(stripped):
                    ok = True
                    break
            return CheckpointResult(name=self.name, passed=ok, explanation=f"commented_out; {'found in comments' if ok else 'NOT found in comments'}")

        return CheckpointResult(name=self.name, passed=False, explanation=f"unknown bug_type: {loc.bug_type}")


@dataclass
class LineRangeValid:
    name: str = "line_range_valid"

    def evaluate(self, state: InvestigationState, output: SuspectCommit) -> CheckpointResult:
        if output.bug_location is None:
            return CheckpointResult(name=self.name, passed=True, explanation="no bug_location to verify")
        loc = output.bug_location
        sha = output.sha if loc.bug_type != "removed" else f"{output.sha}^"
        file_at = _git(state.repo_path, "show", f"{sha}:{loc.file_path}")
        total_lines = len(file_at.splitlines())
        start, end = loc.line_range
        ok = 1 <= start <= end <= total_lines
        return CheckpointResult(
            name=self.name,
            passed=ok,
            explanation=f"range=({start},{end}) total_lines={total_lines}",
        )


@dataclass
class DiffNonempty:
    name: str = "diff_nonempty"

    def evaluate(self, state: InvestigationState, output: Any) -> CheckpointResult:
        # output here is expected to be a DiffSummary or similar; stub returns pass
        return CheckpointResult(name=self.name, passed=True, explanation="stub")


@dataclass
class BranchExists:
    """Every branch cited on a candidate must resolve in the repo."""
    name: str = "branch_exists"

    def evaluate(self, state: InvestigationState, output: SuspectCommit) -> CheckpointResult:
        if not output.branches:
            # No branches cited — nothing to verify, don't penalize.
            return CheckpointResult(name=self.name, passed=True, explanation="no branches cited")
        bad = []
        for branch in output.branches:
            resolved = _git(state.repo_path, "rev-parse", "--verify", branch).strip()
            if not resolved:
                bad.append(branch)
        return CheckpointResult(
            name=self.name,
            passed=not bad,
            explanation=f"unresolved branches: {bad}" if bad else "all branches resolve",
        )


@dataclass
class ConfidenceInRange:
    """Candidate confidence must be a probability in [0.0, 1.0]."""
    name: str = "confidence_in_range"

    def evaluate(self, state: InvestigationState, output: SuspectCommit) -> CheckpointResult:
        ok = 0.0 <= output.confidence <= 1.0
        return CheckpointResult(
            name=self.name,
            passed=ok,
            explanation=f"confidence={output.confidence}",
        )


@dataclass
class BugTypeInEnum:
    """A located bug_type must be one of the allowed labels."""
    name: str = "bug_type_in_enum"
    allowed: tuple[str, ...] = ("introduced", "removed", "commented_out", "legacy")

    def evaluate(self, state: InvestigationState, output: SuspectCommit) -> CheckpointResult:
        if output.bug_location is None:
            # No location yet — nothing to verify, don't penalize.
            return CheckpointResult(name=self.name, passed=True, explanation="no bug_location to verify")
        bug_type = output.bug_location.bug_type
        ok = bug_type in self.allowed
        return CheckpointResult(
            name=self.name,
            passed=ok,
            explanation=f"bug_type={bug_type!r}; allowed={self.allowed}",
        )
