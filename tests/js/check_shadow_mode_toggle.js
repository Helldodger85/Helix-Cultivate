// v1.6.0 Part 5.1 — confirms the Shadow Mode toggle on the Environmental
// Learning Settings tab: only appears when the master toggle
// (thermal_learning_enabled) is on, defaults to on, and carries the exact
// verbatim explanation text.
'use strict';

const assert = require('assert');
const { loadPanelModule } = require('./harness');

const { elements } = loadPanelModule();
const HelixTabSettings = elements['helix-tab-settings'];
assert.ok(HelixTabSettings, 'helix-tab-settings was not registered — was the tag name changed?');

function renderWith(data) {
  const el = new HelixTabSettings();
  el._section = 'learning';
  el.hass = {};
  el.data = data;
  return el.shadowRoot.innerHTML;
}

// ── Master toggle off: Shadow Mode toggle must not appear at all ───────────
const offHtml = renderWith({ entry_id: 'e1', thermal_learning_enabled: false });
assert.ok(!offHtml.includes('learning-shadow-toggle'),
  'Shadow Mode toggle must be hidden entirely while Environmental Learning is off');

// ── Master toggle on, shadow mode unset (fresh enable): defaults to on ─────
const freshHtml = renderWith({ entry_id: 'e1', thermal_learning_enabled: true });
assert.ok(freshHtml.includes('id="learning-shadow-toggle"'),
  'Shadow Mode toggle must appear once Environmental Learning is on');
assert.ok(/id="learning-shadow-toggle"[^>]*checked/.test(freshHtml),
  'Shadow Mode must default to checked (on) when not explicitly set to false');

const explanation =
  "While on, the model keeps learning and predicting, but never touches real control — you " +
  "can watch what it would have done before trusting it with your actual setpoints.";
assert.ok(freshHtml.replace(/\s+/g, ' ').includes(explanation.replace(/\s+/g, ' ')),
  'Shadow Mode explanatory copy missing or not verbatim');

// ── Explicitly turned off ───────────────────────────────────────────────────
const offShadowHtml = renderWith({
  entry_id: 'e1', thermal_learning_enabled: true, learning_shadow_mode: false,
});
assert.ok(!/id="learning-shadow-toggle"[^>]*checked/.test(offShadowHtml),
  'Shadow Mode toggle must render unchecked when learning_shadow_mode is explicitly false');

console.log('OK: Shadow Mode toggle gated on master toggle, defaults on, verbatim copy present.');
