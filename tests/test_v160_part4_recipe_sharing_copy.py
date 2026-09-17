"""Test for v1.6.0 Part 4: Recipe Sharing's Export/Import copy must
accurately describe its real, verified scope.

Investigation of stage_manager.py confirmed export_current_recipe() and
import_recipe() operate on ALL stages (STAGE_SEQUENCE) as a single YAML
document — the entire grow plan, not one stage — and that there is no
database, directory, or strain-lookup feature; it is a plain file
export/import meant for pasting into a forum post or shared folder.

Frontend behavior in this project is verified through a Node-based logic
check rather than a browser test suite (see README's Known Issues) — this
test shells out to tests/js/check_recipe_sharing_copy.js, which instantiates
the actual shipped <helix-tab-cycle> custom element and inspects the real
rendered markup for the exact copy.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "tests" / "js" / "check_recipe_sharing_copy.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is required for this frontend check"
)


def test_recipe_sharing_copy_matches_verified_whole_plan_scope():
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
    assert "OK: Recipe Sharing copy accurately reflects" in result.stdout


def test_export_current_recipe_covers_every_stage_not_a_single_stage():
    """Backend verification backing the frontend copy's claim: export
    really is whole-plan, not per-stage."""
    from custom_components.helix_cultivate.stage_manager import STAGE_SEQUENCE
    import yaml

    coord = pytest.importorskip("unittest.mock").MagicMock()
    from custom_components.helix_cultivate.stage_manager import StageManager

    sm = StageManager.__new__(StageManager)
    sm._config = {}

    def fake_profile(stage):
        return {
            "vpd_kpa": 1.0, "temp_c": 24.0, "rh_pct": 60.0, "photoperiod_h": 18.0,
        }

    sm._profile = fake_profile
    sm._duration = lambda stage: 7

    yaml_text = sm.export_current_recipe()
    data = yaml.safe_load(yaml_text)

    assert set(data["stages"].keys()) == set(STAGE_SEQUENCE), (
        "export_current_recipe must include every stage in one document, "
        "not a single stage"
    )
