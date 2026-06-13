"""JSON persistence for InvestigationState — enables checkpoint replay.

After every loop transition the loop calls `save(state)`. To replay from a
stage, the user (or a CLI flag) calls `load(investigation_id, stage)` and
resumes the loop from that node.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from harness.materials.state import InvestigationState, Stage

ROOT = Path("./investigations")


def _dir_for(investigation_id: str) -> Path:
    d = ROOT / investigation_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(state: InvestigationState) -> Path:
    """Persist state to ./investigations/{id}/state_{stage}.json"""
    d = _dir_for(state.investigation_id)
    path = d / f"state_{state.current_stage.value}.json"
    path.write_text(state.model_dump_json(indent=2))
    # Also write a 'latest' symlink-style file for quick lookup
    (d / "latest.json").write_text(state.model_dump_json(indent=2))
    return path


def load(investigation_id: str, stage: Optional[Stage] = None) -> InvestigationState:
    """Load state from disk. If stage is None, load `latest.json`."""
    d = _dir_for(investigation_id)
    filename = f"state_{stage.value}.json" if stage else "latest.json"
    path = d / filename
    if not path.exists():
        raise FileNotFoundError(f"No saved state at {path}")
    return InvestigationState.model_validate_json(path.read_text())


def list_stages(investigation_id: str) -> list[Stage]:
    """List which stages have been persisted for an investigation."""
    d = _dir_for(investigation_id)
    stages = []
    for p in d.glob("state_*.json"):
        stage_name = p.stem.replace("state_", "")
        try:
            stages.append(Stage(stage_name))
        except ValueError:
            continue
    return stages
