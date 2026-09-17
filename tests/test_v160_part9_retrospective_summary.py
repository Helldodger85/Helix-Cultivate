"""Tests for v1.6.0 Part 9: the Environmental Learning Settings tab's
trailing-window retrospective summary — an aggregate ("Over the last 7
days, shadow and real control agreed on direction X% of the time; average
predicted adjustment when they disagreed was Y°C"), never a live graph.
Derived from the same logged comparison data as Part 6's chart.
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.helix_cultivate.learning_engine import LearningEngine

REPO_ROOT = Path(__file__).resolve().parent.parent


def _row(hours_ago, generic, blended):
    ts = (dt_util.utcnow() - timedelta(hours=hours_ago)).isoformat()
    return {
        "zone": "conditioning", "ts": ts,
        "shadow_generic_bias_c": generic, "shadow_blended_bias_c": blended,
    }


class TestShadowRetrospectiveSummary:
    def test_none_when_no_store(self, mock_coord):
        mock_coord.hass.data = {"helix_cultivate": {}}
        engine = LearningEngine(mock_coord)
        assert engine.compute_shadow_retrospective_summary() is None

    def test_none_when_no_qualifying_rows(self, mock_coord):
        store = MagicMock()
        store.get_hourly_logs = MagicMock(return_value=[])
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)
        assert engine.compute_shadow_retrospective_summary() is None

    def test_known_agreement_rate_computed_correctly(self, mock_coord):
        # 3 agreeing rows (same sign), 1 disagreeing row (opposite sign,
        # |blended|=2.0) -> 75% agreement, avg disagreement magnitude 2.0.
        rows = [
            _row(1, 0.5, 0.6),    # agree (both positive)
            _row(2, -0.3, -0.4),  # agree (both negative)
            _row(3, 0.2, 0.1),    # agree (both positive)
            _row(4, 0.5, -2.0),   # disagree
        ]
        store = MagicMock()
        store.get_hourly_logs = MagicMock(return_value=rows)
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        summary = engine.compute_shadow_retrospective_summary()

        assert summary["sample_count"] == 4
        assert summary["agreement_pct"] == pytest.approx(75.0)
        assert summary["avg_disagreement_bias_c"] == pytest.approx(2.0)
        assert summary["trailing_days"] == 7.0

    def test_rows_missing_bias_fields_are_skipped(self, mock_coord):
        rows = [
            _row(1, 0.5, 0.6),
            {"zone": "conditioning", "ts": dt_util.utcnow().isoformat(),
             "shadow_generic_bias_c": None, "shadow_blended_bias_c": None},
        ]
        store = MagicMock()
        store.get_hourly_logs = MagicMock(return_value=rows)
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        summary = engine.compute_shadow_retrospective_summary()
        assert summary["sample_count"] == 1

    def test_rows_outside_trailing_window_are_excluded(self, mock_coord):
        rows = [
            _row(1, 0.5, 0.6),      # within window
            _row(24 * 10, 0.5, -3.0),  # 10 days ago -> excluded from 7-day window
        ]
        store = MagicMock()
        store.get_hourly_logs = MagicMock(return_value=rows)
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        summary = engine.compute_shadow_retrospective_summary(trailing_days=7.0)
        assert summary["sample_count"] == 1
        assert summary["agreement_pct"] == pytest.approx(100.0)

    def test_all_agree_gives_zero_avg_disagreement(self, mock_coord):
        rows = [_row(1, 0.5, 0.6), _row(2, 0.4, 0.3)]
        store = MagicMock()
        store.get_hourly_logs = MagicMock(return_value=rows)
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        summary = engine.compute_shadow_retrospective_summary()
        assert summary["agreement_pct"] == pytest.approx(100.0)
        assert summary["avg_disagreement_bias_c"] == 0.0


CHECK_SCRIPT = REPO_ROOT / "tests" / "js" / "check_retrospective_summary.js"

pytestmark_js = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is required for this frontend check"
)


@pytestmark_js
def test_retrospective_summary_frontend_rendering():
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
    assert "OK: Settings tab retrospective summary" in result.stdout
