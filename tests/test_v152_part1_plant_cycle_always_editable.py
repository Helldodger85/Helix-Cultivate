"""Test for v1.5.2 Part 1: the Plant Cycle tab's "No Active Cycle" empty
state was specified too broadly in v1.2.9, ending up blocking the entire
Grow Stage Timeline's stage-by-stage configuration — a grower could not
view, plan, or tune any stage's targets unless a cycle was already
running. The tab is now split into an always-visible, cycle_state-only
status panel at the very top, with the full timeline/profile editor always
visible and editable beneath it regardless of state.

Frontend behavior in this project is verified through code review and a
Node-based logic check rather than a browser test suite (see README's
Known Issues) — this test shells out to tests/js/check_plant_cycle_always_editable.js,
which instantiates the actual shipped <helix-tab-cycle> custom element (via
a dependency-free sandbox, no jsdom) with both cycle_state values and
inspects the real rendered markup.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "tests" / "js" / "check_plant_cycle_always_editable.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is required for this frontend check"
)


def test_plant_cycle_status_panel_and_timeline_split_correctly():
    result = subprocess.run(
        ["node", str(CHECK_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Node check failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK: Plant Cycle status panel and Grow Stage Timeline" in result.stdout
