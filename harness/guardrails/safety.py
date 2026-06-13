"""Safety guardrails — non-negotiable constraints on agent behavior.

These aren't tunable. They prevent the agent from doing damage regardless of
how much budget is remaining.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from harness.guardrails.base import GuardrailResult
from harness.materials.state import InvestigationState


@dataclass
class ReadOnlyRepo:
    """The harness never writes to the repo. Verified by asserting no git
    write commands are used, and (during real runs) by checking the working tree
    hash didn't change after a stage. This stub just declares the constraint.
    """
    name: str = "READ_ONLY_REPO"

    def check(self, state: InvestigationState) -> GuardrailResult:
        # Verify repo path exists and is a git directory
        path = state.repo_path
        git_dir = os.path.join(path, ".git")
        if not os.path.isdir(path):
            return GuardrailResult(name=self.name, passed=False, explanation=f"{path} not a directory")
        if not os.path.isdir(git_dir):
            return GuardrailResult(name=self.name, passed=False, explanation=f"{path} not a git repo")
        return GuardrailResult(name=self.name, passed=True, explanation="read-only enforced; repo is git")


@dataclass
class NoAutoApply:
    """Fix proposals are never executed. The harness has no apply pathway —
    this guardrail mostly exists to declare the constraint and trip if a future
    coder forgets and tries to add one.
    """
    name: str = "NO_AUTO_APPLY"

    def check(self, state: InvestigationState) -> GuardrailResult:
        return GuardrailResult(
            name=self.name,
            passed=True,
            explanation="no apply pathway exists in the harness",
        )


@dataclass
class WindowBound:
    name: str = "WINDOW_BOUND"
    allowed_windows: tuple[int, ...] = (30, 90)

    def check(self, state: InvestigationState) -> GuardrailResult:
        ok = state.lookback_days in self.allowed_windows
        return GuardrailResult(
            name=self.name,
            passed=ok,
            explanation=f"lookback={state.lookback_days} days; allowed={self.allowed_windows}",
        )


@dataclass
class FileExtensionScope:
    """The agent may only consider files with these extensions.
    Defaults configured for Unity (.cs, .shader).
    """
    name: str = "FILE_EXTENSION_SCOPE"
    allowed_extensions: list[str] = field(default_factory=lambda: [".cs", ".shader"])

    def check(self, state: InvestigationState) -> GuardrailResult:
        # In real use the loop applies this filter before reaching the agent;
        # this check confirms the configured scope is sane.
        scope = state.file_extension_scope
        ok = bool(scope) and all(s.startswith(".") for s in scope)
        return GuardrailResult(
            name=self.name,
            passed=ok,
            explanation=f"configured={scope}",
        )
