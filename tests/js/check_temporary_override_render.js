// v1.5.1 — Node-based check (no jsdom/browser dependency, matching this
// project's established "verify frontend via syntax checking, not a
// browser test suite" approach) that the Temporary Override section's
// Light Intensity slider is entirely absent — not merely disabled — when
// the Night context is selected, while Temp Setpoint and VPD Target
// remain present in both contexts. Runs helix-panel.js in a minimal
// sandboxed context (just enough for its module-level class declarations
// to parse without a real browser) and calls the extracted, pure
// _renderOverrideSlidersHtml() function directly with both contexts.
//
// Invoked from tests/test_v151_hide_light_override_on_night.py via
// subprocess so it participates in `pytest tests/`'s full-suite run.
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const panelPath = path.join(__dirname, '..', '..', 'custom_components', 'helix_cultivate', 'www', 'helix-panel.js');
const src = fs.readFileSync(panelPath, 'utf8');

const noopStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};
const context = {
  HTMLElement: class {},
  customElements: { define: () => {} },
  localStorage: noopStorage,
  sessionStorage: noopStorage,
  window: { matchMedia: () => ({ matches: false, addEventListener: () => {} }) },
  document: {
    createElement: () => ({ style: {}, setAttribute: () => {}, appendChild: () => {} }),
    addEventListener: () => {},
    head: { appendChild: () => {} },
  },
  console,
};
vm.createContext(context);
new vm.Script(src, { filename: 'helix-panel.js' }).runInContext(context);

assert.strictEqual(
  typeof context._renderOverrideSlidersHtml, 'function',
  '_renderOverrideSlidersHtml was not found at module scope — was it renamed or removed?'
);

const args = (overrideCtx) => [overrideCtx, 24.0, 1.0, 100.0, null, null, null];

const dayHtml = context._renderOverrideSlidersHtml(...args('day'));
const nightHtml = context._renderOverrideSlidersHtml(...args('night'));

// Day: all three sliders present.
assert.ok(dayHtml.includes('id="override-temp-sl"'), 'Day: Temp Setpoint slider missing');
assert.ok(dayHtml.includes('id="override-vpd-sl"'), 'Day: VPD Target slider missing');
assert.ok(dayHtml.includes('id="override-light-sl"'), 'Day: Light Intensity slider missing');

// Night: Light Intensity slider entirely absent; Temp/VPD still present.
assert.ok(!nightHtml.includes('id="override-light-sl"'), 'Night: Light Intensity slider must be entirely absent, but was found');
assert.ok(!nightHtml.includes('override-light-val'), 'Night: Light Intensity value display must be entirely absent, but was found');
assert.ok(nightHtml.includes('id="override-temp-sl"'), 'Night: Temp Setpoint slider missing');
assert.ok(nightHtml.includes('id="override-vpd-sl"'), 'Night: VPD Target slider missing');

// Switching back to Day restores it (proves this is live/derived from the
// context argument, not some one-way removal).
const dayAgainHtml = context._renderOverrideSlidersHtml(...args('day'));
assert.ok(dayAgainHtml.includes('id="override-light-sl"'), 'Day (after Night): Light Intensity slider not restored');

// The badge line for an active override must also disappear when hidden,
// not linger detached from its (now-absent) slider.
const nightWithActiveLight = context._renderOverrideSlidersHtml('night', 24.0, 1.0, 100.0, null, null, 55.0);
assert.ok(!nightWithActiveLight.includes('override-light'), 'Night: an active light override must not leak any light-related markup');

console.log('OK: Light Intensity override slider hidden on Night, present on Day; Temp/VPD unaffected.');
