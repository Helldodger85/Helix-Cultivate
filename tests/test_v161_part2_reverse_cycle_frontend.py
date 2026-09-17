"""Test for v1.6.1 Part 2's frontend fix: HelixTabConditioning's hardware-
mapping form now actually includes the Reverse Cycle Unit toggle in its
Save payload — see tests/test_v161_part2_reverse_cycle_persistence.py for
the backend-persistence half of this bug (which was already correct) and
tests/js/check_reverse_cycle_toggle_save.js's own header comment for the
full root-cause writeup.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "tests" / "js" / "check_reverse_cycle_toggle_save.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is required for this frontend check"
)


def test_conditioning_room_save_payload_includes_reverse_cycle_toggle():
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
    assert "OK: Conditioning Room hardware form now includes" in result.stdout
