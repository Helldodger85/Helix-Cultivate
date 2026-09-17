"""Test for v1.6.0 Parts 6/7/8 frontend behavior:

Part 8: the current-moment Shadow readout near Conditioning Room's
Setpoints card — correct "applied"/"not applied" phrasing per Shadow Mode,
hidden entirely when Environmental Learning's master toggle is off.

Part 6/7: the comparison chart (24h/48h/7d, no "Live") and the weather-event
log rendered directly beneath it, only appearing once Environmental
Learning is on.

Frontend behavior in this project is verified through a Node-based logic
check rather than a browser test suite (see README's Known Issues) — this
test shells out to tests/js/check_shadow_comparison_chart.js, which
instantiates the actual shipped custom elements and inspects the real
rendered markup.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "tests" / "js" / "check_shadow_comparison_chart.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is required for this frontend check"
)


def test_shadow_readout_and_comparison_chart_render_correctly():
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
    assert "OK: Shadow readout phrasing/gating" in result.stdout
