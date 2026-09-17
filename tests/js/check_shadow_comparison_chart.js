// v1.6.0 Parts 6/7/8 — confirms:
//  - Part 8: the current-moment Shadow readout renders near the Setpoints
//    card with correct phrasing for Shadow Mode on/off, and is hidden
//    entirely when Environmental Learning's master toggle is off.
//  - Part 6/7: the comparison chart + weather-event log element only
//    appears once Environmental Learning is on, offers 24h/48h/7d buttons
//    with no "Live" option, and renders weather events beneath the chart.
'use strict';

const assert = require('assert');
const { loadPanelModule } = require('./harness');

const { elements } = loadPanelModule();
const HelixTabConditioning = elements['helix-tab-conditioning'];
const HelixShadowComparisonCard = elements['helix-shadow-comparison-card'];
assert.ok(HelixTabConditioning, 'helix-tab-conditioning was not registered');
assert.ok(HelixShadowComparisonCard, 'helix-shadow-comparison-card was not registered');

function renderConditioning(data) {
  const el = new HelixTabConditioning();
  el.hass = {};
  el.data = data;
  return el.shadowRoot.innerHTML;
}

const baseData = {
  entry_id: 'e1', zone1_name: 'Conditioning Room',
  lung_temp_c: 22.0, lung_rh_pct: 55, temp_setpoint: 24, zone1_rh_setpoint: 55,
};

// ── Master toggle off: readout and chart both absent ───────────────────────
const offHtml = renderConditioning({
  ...baseData, thermal_learning_enabled: false,
  shadow_prediction: { predicted_indoor_temp_c: 23.5, confidence: 0.72, shadow_mode: true },
});
assert.ok(!offHtml.includes('Shadow suggestion'),
  'Shadow readout must be hidden entirely when master toggle is off');
assert.ok(!offHtml.includes('helix-shadow-comparison-card'),
  'Comparison chart element must be absent when master toggle is off');

// ── Master toggle on, Shadow Mode ON: "not applied" phrasing ───────────────
const shadowOnHtml = renderConditioning({
  ...baseData, thermal_learning_enabled: true,
  shadow_prediction: { predicted_indoor_temp_c: 23.5, confidence: 0.72, shadow_mode: true },
});
assert.ok(shadowOnHtml.includes('Shadow suggestion: 23.5°C'),
  'Shadow readout must show the predicted temperature');
assert.ok(shadowOnHtml.includes('confidence: 72%'),
  'Shadow readout must show confidence as a percentage');
assert.ok(shadowOnHtml.includes('not applied'),
  'Shadow Mode ON must render "not applied"');
assert.ok(shadowOnHtml.includes('<helix-shadow-comparison-card'),
  'Comparison chart element must be present when master toggle is on');

// ── Master toggle on, Shadow Mode OFF: "applied" phrasing ──────────────────
const shadowOffHtml = renderConditioning({
  ...baseData, thermal_learning_enabled: true,
  shadow_prediction: { predicted_indoor_temp_c: 23.9, confidence: 0.9, shadow_mode: false },
});
assert.ok(shadowOffHtml.includes('— applied') || shadowOffHtml.includes('applied'),
  'Shadow Mode OFF must render "applied" (not "not applied")');
assert.ok(!/not applied/.test(shadowOffHtml),
  'Shadow Mode OFF must NOT render "not applied"');

// ── Comparison chart itself: no Live button, has 24h/48h/7d ────────────────
const chartEl = new HelixShadowComparisonCard();
chartEl._rows = [
  { ts: '2026-01-01T00:00:00+00:00', indoor_temp_c: 22.0, shadow_predicted_indoor_temp_c: 22.5 },
  { ts: '2026-01-01T01:00:00+00:00', indoor_temp_c: 22.2, shadow_predicted_indoor_temp_c: 22.6 },
];
chartEl._events = [
  { ts: '2026-01-01T00:30:00+00:00', message: 'Rain expected within the next hour (75% chance)',
    correlated_bias_c: 1.3 },
];
chartEl._render();
const chartHtml = chartEl.shadowRoot.innerHTML;

assert.ok(!/>\s*Live\s*</.test(chartHtml) && !chartHtml.includes('data-tf="live"'),
  'Comparison chart must NOT offer a Live timeframe option');
assert.ok(chartHtml.includes('data-tf="24h"') && chartHtml.includes('data-tf="48h"') && chartHtml.includes('data-tf="7d"'),
  'Comparison chart must offer 24h/48h/7d timeframe buttons');
assert.ok(chartHtml.includes('Rain expected within the next hour'),
  'Weather event log must render beneath the chart');

console.log('OK: Shadow readout phrasing/gating and comparison chart/weather-log rendering all correct.');
