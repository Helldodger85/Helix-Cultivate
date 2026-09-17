"""Test for v1.6.1 Part 1: the Conditioning Room comparison chart's
~30-second flicker.

Root cause (confirmed by reading the real code): <helix-panel> pushes
`.hass =` / `.data =` onto the active tab element on every coordinator tick
(COORDINATOR_UPDATE_INTERVAL = 30s, const.py), and
HelixTabConditioning.set data() rebuilds its entire shadowRoot.innerHTML on
every such push. <helix-shadow-comparison-card> used to be embedded
directly in that regenerated markup, so it was destroyed and recreated
from scratch on every tick — a fresh instance's constructor reset its
_rows/_events to empty, and its `hass` setter's one-time-fetch guard fired
again on the new instance, producing an empty -> loading -> loaded flash
every 30 seconds (this chart, unlike the sparkline cards, has no
synchronous 'live' mode, so it flickered on literally every tick).

The fix reuses a single chart instance across renders (the same
reuse-in-place pattern <helix-panel>'s own _update() already applies to
whole tab elements) instead of recreating it — see the constructor comment
on HelixTabConditioning._shadowComparisonEl in helix-panel.js.

This shells out to tests/js/check_shadow_comparison_persistence.js, which
instantiates the real shipped custom elements and proves: the same chart
instance survives repeated `.data =` pushes, and it fetches at most once
across them (not once per tick).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "tests" / "js" / "check_shadow_comparison_persistence.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is required for this frontend check"
)


def test_comparison_chart_instance_persists_and_fetches_once():
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
    assert "OK: comparison chart instance persists" in result.stdout
