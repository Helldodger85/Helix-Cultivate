"""Helix Cultivate — Environmental Learning System's fitted regression
(v1.4.1 Part 4).

Replaces the original per-zone bucketed-running-mean model (which could
only answer for a condition bucket it had seen before) with a genuine
ordinary least-squares multi-variable regression, fit across every input
variable at once — outdoor temperature, time-of-day, season, light on/off
state and brightness, and an approximate occupied/heated-hours flag. This
lets the model produce a sensible prediction for a combination of
conditions it hasn't seen in that exact combination before, by combining
the separately-learned effect of each variable, rather than requiring that
exact combination to already have accumulated its own samples.

Deliberately built on numpy alone (an ordinary least-squares solve plus a
leverage-adjusted prediction-interval estimate) rather than a heavier
machine-learning framework — this system is meant to stay inspectable, not
become a black box. The one-sided z-value used for the prediction interval
below is an approximation of a Student's-t quantile (exact quantiles would
need scipy); that approximation is deliberate, not an oversight.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np

from .const import (
    MIN_REGRESSION_SAMPLES,
    REGRESSION_CONFIDENCE_Z,
    REGRESSION_PI_SATURATION_C,
)

# Cyclical (sin/cos) encodings for hour-of-day and month avoid the
# discontinuity a raw 0-23 / 1-12 integer would introduce at the wrap
# (23:00 and 00:00 are one hour apart, not twenty-three).
FEATURE_NAMES: tuple[str, ...] = (
    "intercept",
    "outdoor_temp_c",
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos",
    "lights_on",
    "light_pct",
    "occupied",
)


def build_feature_vector(
    *,
    outdoor_temp_c: Optional[float],
    hour_of_day: Optional[int],
    month: Optional[int],
    lights_on: bool,
    light_pct: float,
    occupied: bool,
) -> Optional[list[float]]:
    """Build one row of the design matrix (or a query point). Returns None
    when outdoor_temp_c — the single most important predictor — is
    missing; a row/query with no outdoor reading at all isn't worth
    fitting or predicting against. hour_of_day/month default to a neutral
    midday/mid-year point when not supplied, rather than failing outright,
    since a caller may reasonably not always have them handy.
    """
    if outdoor_temp_c is None:
        return None
    hour = hour_of_day if hour_of_day is not None else 12
    mon = month if month is not None else 6
    hour_rad = 2.0 * math.pi * (hour / 24.0)
    month_rad = 2.0 * math.pi * ((mon - 1) / 12.0)
    return [
        1.0,
        float(outdoor_temp_c),
        math.sin(hour_rad),
        math.cos(hour_rad),
        math.sin(month_rad),
        math.cos(month_rad),
        1.0 if lights_on else 0.0,
        float(light_pct) / 100.0,
        1.0 if occupied else 0.0,
    ]


def fit_ols(rows: list[list[float]], targets: list[float]) -> Optional[dict[str, Any]]:
    """Fit an ordinary least-squares regression across every row/target
    pair. Returns None (Part 4.4's safe fallback) when there isn't enough
    data yet, or the design matrix is rank-deficient (a genuinely singular
    fit) — trusting an underdetermined or singular fit would produce a
    falsely-confident prediction rather than honestly deferring to the
    generic fallback.
    """
    n = len(rows)
    p = len(FEATURE_NAMES)
    if n < max(MIN_REGRESSION_SAMPLES, p + 3) or n != len(targets):
        return None

    x_matrix = np.array(rows, dtype=float)
    y_vector = np.array(targets, dtype=float)

    if np.linalg.matrix_rank(x_matrix) < p:
        return None

    try:
        coefficients, _, _, _ = np.linalg.lstsq(x_matrix, y_vector, rcond=None)
        xtx_inv = np.linalg.inv(x_matrix.T @ x_matrix)
    except np.linalg.LinAlgError:
        return None

    dof = n - p
    if dof <= 0:
        return None
    fitted = x_matrix @ coefficients
    rss = float(np.sum((y_vector - fitted) ** 2))
    sigma = math.sqrt(rss / dof)

    return {
        "coefficients": coefficients.tolist(),
        "xtx_inv": xtx_inv.tolist(),
        "sigma": sigma,
        "n": n,
    }


def predict_with_confidence(model: dict[str, Any], x0: list[float]) -> tuple[float, float]:
    """Returns (predicted_response, confidence in [0.0, 1.0]) for one query
    point. Confidence is derived from the fitted model's own
    leverage-adjusted prediction-interval half-width (Part 4.3) — a wide
    interval (genuinely uncertain for this input combination) yields low
    confidence, a narrow one (well-supported by data near this point)
    yields confidence approaching 1.0. Never raises on malformed model
    input; returns (0.0, 0.0) instead, so a corrupted/incompatible stored
    model defers to the safe generic fallback exactly like "no model yet"
    does, rather than crashing a control tick.
    """
    try:
        coefficients = np.array(model["coefficients"], dtype=float)
        xtx_inv = np.array(model["xtx_inv"], dtype=float)
        sigma = float(model["sigma"])
        x = np.array(x0, dtype=float)
        if x.shape != coefficients.shape:
            return 0.0, 0.0

        predicted = float(x @ coefficients)
        leverage = float(x @ xtx_inv @ x)
        pred_variance = sigma ** 2 * (1.0 + max(0.0, leverage))
        pi_half_width = REGRESSION_CONFIDENCE_Z * math.sqrt(max(0.0, pred_variance))

        confidence = 1.0 - (pi_half_width / REGRESSION_PI_SATURATION_C)
        confidence = max(0.0, min(1.0, confidence))
        return predicted, confidence
    except (KeyError, ValueError, TypeError):
        return 0.0, 0.0
