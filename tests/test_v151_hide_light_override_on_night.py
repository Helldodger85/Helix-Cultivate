"""Test for v1.5.1: the Temporary Override section's Light Intensity
slider must be entirely absent (not disabled) when the Day/Night toggle
is set to Night — v1.5.0 shipped it rendering unconditionally in both
contexts, contradicting the original spec.

Frontend behavior in this project is verified through code review and a
Node-based syntax/logic check rather than a browser test suite (see
README's Known Issues) — this test shells out to a small, dependency-free
Node script (tests/js/check_temporary_override_render.js) that evaluates
the actual shipped helix-panel.js and calls the extracted, pure
_renderOverrideSlidersHtml() function directly with both Day and Night
contexts, so this is a real check against the shipped markup rather than
a hand-copied re-implementation of the fix.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "tests" / "js" / "check_temporary_override_render.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is required for this frontend check"
)


def test_light_intensity_override_hidden_on_night_shown_on_day():
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
    assert "OK: Light Intensity override slider hidden on Night" in result.stdout
