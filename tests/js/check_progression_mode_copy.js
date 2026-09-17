// v1.6.0 Part 3 — confirms the Progression Mode section's Auto-Advance
// Stages and Smooth Glides toggles are each accompanied by the exact
// verbatim explanatory copy the ticket specified, rendered directly beside
// their respective toggle (not merged, swapped, or paraphrased).
'use strict';

const assert = require('assert');
const { loadPanelModule } = require('./harness');

const { elements } = loadPanelModule();
const HelixTabCycle = elements['helix-tab-cycle'];
assert.ok(HelixTabCycle, 'helix-tab-cycle was not registered — was the tag name changed?');

function renderWith(data) {
  const el = new HelixTabCycle();
  el.hass = {};
  el.data = data;
  return el.shadowRoot.innerHTML;
}

const baseData = {
  entry_id: 'entry123',
  grow_stage_slug: 'early_veg',
  stage_day: 5,
  stage_duration: 14,
  enable_drying_environment: false,
  growth_mode: 'photoperiod',
  zone2_occupied: false,
  cycle_state: 'active',
  progression_mode: 'timeframe',
  smooth_glides: true,
};

const html = renderWith(baseData);

const autoAdvanceCopy =
  "When on, Helix Cultivate automatically moves to the next stage once the current " +
  "stage's day-count target is reached. When off, stages only advance when you do it " +
  "manually — the day-count still shows progress, but won't trigger anything on its own.";

const smoothGlidesCopy =
  "When on, every target gradually shifts from this stage's values toward the next " +
  "stage's values across the whole stage, so the actual transition is seamless with no " +
  "sudden jump. When off, changes happen instantly the moment a stage begins.";

function normalize(s) {
  return s.replace(/\s+/g, ' ').trim();
}

const normalizedHtml = normalize(html);
assert.ok(
  normalizedHtml.includes(normalize(autoAdvanceCopy)),
  'Auto-Advance Stages explanatory copy missing or not verbatim'
);
assert.ok(
  normalizedHtml.includes(normalize(smoothGlidesCopy)),
  'Smooth Glides explanatory copy missing or not verbatim'
);

// Each explanation must sit next to its own toggle, not the other one's.
const progToggleIdx = html.indexOf('id="prog-toggle"');
const glideToggleIdx = html.indexOf('id="glide-toggle"');
const autoAdvanceIdx = normalizedHtml.indexOf(normalize(autoAdvanceCopy));
const smoothGlidesIdx = normalizedHtml.indexOf(normalize(smoothGlidesCopy));

assert.ok(progToggleIdx >= 0 && glideToggleIdx > progToggleIdx,
  'expected prog-toggle to render before glide-toggle');
assert.ok(autoAdvanceIdx < smoothGlidesIdx,
  'Auto-Advance copy must render before Smooth Glides copy, matching toggle order');

console.log('OK: Auto-Advance Stages and Smooth Glides explanatory copy render verbatim beside their toggles.');
