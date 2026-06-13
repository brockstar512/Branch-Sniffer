"""CLI entry point — run an investigation from the terminal.

Usage:
    python cli.py --repo /path/to/repo --bug "camera flickers on jump"
    python cli.py --repo . --bug "test" --agent grep
"""
from __future__ import annotations

import argparse
import sys

from agents.claude_agent import ClaudeAgent
from agents.grep_agent import GrepAgent
from harness.loop import run
from harness.materials.state import BugReport, InvestigationState


def main() -> int:
    parser = argparse.ArgumentParser(description="Dog — sniff out the commit that broke your build.")
    parser.add_argument("--repo", required=True, help="Path to local git repository")
    parser.add_argument("--bug", required=True, help="Bug description / observed symptoms")
    parser.add_argument("--lookback", type=int, default=30, choices=[30, 90], help="Days to look back")
    parser.add_argument("--agent", default="claude", choices=["claude", "grep"], help="Which agent to run")
    parser.add_argument(
        "--scope",
        nargs="*",
        default=[".cs", ".shader"],
        help="File extensions in scope (default: Unity)",
    )
    parser.add_argument("--reproduced", action="store_true", help="Mark bug as reproduced")
    args = parser.parse_args()

    state = InvestigationState(
        bug_report=BugReport(description=args.bug),
        repo_path=args.repo,
        lookback_days=args.lookback,
        file_extension_scope=args.scope,
        focus_topic=args.bug,
        reproduced=args.reproduced if args.reproduced else None,
    )

    agent = ClaudeAgent() if args.agent == "claude" else GrepAgent()

    print(f"Yo dog, starting investigation {state.investigation_id[:8]}...")
    print(f"  agent={agent.name} repo={args.repo} lookback={args.lookback}d scope={args.scope}")
    print()

    final = run(state, agent)

    print()
    print(f"Done dog. Final stage: {final.current_stage.value}")
    print(f"Candidates: {len(final.candidate_commits)}")
    print(f"Alarms raised: {len(final.alarm_history)}")
    print(f"Checkpoints evaluated: {len(final.checkpoint_history)}")
    print(f"State saved at: ./investigations/{final.investigation_id}/")

    return 0


if __name__ == "__main__":
    sys.exit(main())
