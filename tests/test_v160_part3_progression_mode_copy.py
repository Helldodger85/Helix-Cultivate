"""Test for v1.6.0 Part 3: the Auto-Advance Stages and Smooth Glides toggles
in the Progression Mode section now carry verbatim explanatory copy directly
beside each, so a grower understands what each toggle actually does without
guessing from the label alone.

Frontend behavior in this project is verified through a Node-based logic
check rather than a browser test suite (see README's Known Issues) — this
test shells out to tests/js/check_progression_mode_copy.js, which
instantiates the actual shipped <helix-tab-cycle> custom element and
inspects the real rendered markup for the exact copy.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "tests" / "js" / "check_progression_mode_copy.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is required for this frontend check"
)


def test_progression_mode_explanatory_copy_renders_verbatim():
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
    assert "OK: Auto-Advance Stages and Smooth Glides explanatory copy" in result.stdout
