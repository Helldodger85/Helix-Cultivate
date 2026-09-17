// v1.6.1 Part 1 — regression test for the Conditioning Room comparison
// chart's ~30-second flicker.
//
// Root cause (confirmed by reading the real code, not assumed): the root
// <helix-panel> pushes `.hass =` / `.data =` onto the active tab element on
// every coordinator tick (COORDINATOR_UPDATE_INTERVAL = 30s, const.py), and
// HelixTabConditioning.set data() rebuilds its ENTIRE shadowRoot.innerHTML
// on every such push — same as every other tab. Before this fix,
// <helix-shadow-comparison-card> was embedded directly in that regenerated
// markup, so it was destroyed and recreated from scratch on every single
// tick: a fresh instance's constructor reset _rows/_events to empty, and
// its `hass` setter's "first assignment" fetch fired again immediately,
// producing an empty -> loading -> loaded flash every 30 seconds — 100% of
// the time, since (unlike <helix-sparkline-card>, which defaults to a
// synchronous 'live' mode) this chart has no live mode and is always in
// async-fetch mode.
//
// This is the same general bug class the codebase already hit once for
// <helix-sparkline-card> (a full-innerHTML-rebuild destroying child
// instance state — see the "Part 1.3" comments in helix-panel.js), and the
// same pattern <helix-panel>'s own _update() already avoids for whole tab
// elements by reusing them across ticks instead of recreating them. The
// fix applies that identical reuse-in-place pattern one level deeper: a
// single <helix-shadow-comparison-card> instance is created once, cached
// on the tab element, and re-mounted into a fresh placeholder slot on every
// render instead of being torn down — so this test proves the SAME
// instance survives repeated coordinator ticks and is fetched from at
// most once, not once per tick.
'use strict';

const assert = require('assert');
const { loadPanelModule } = require('./harness');

const { elements } = loadPanelModule();
const HelixTabConditioning = elements['helix-tab-conditioning'];
assert.ok(HelixTabConditioning, 'helix-tab-conditioning was not registered');

const baseData = {
  entry_id: 'e1', zone1_name: 'Conditioning Room', thermal_learning_enabled: true,
  lung_temp_c: 22.0, lung_rh_pct: 55, temp_setpoint: 24, zone1_rh_setpoint: 55,
};

async function main() {
  let callCount = 0;
  const fakeHass = {
    callWS: async (msg) => {
      if (msg.type === 'helix_cultivate/get_shadow_comparison_data') callCount++;
      return { rows: [], weather_events: [] };
    },
  };

  const el = new HelixTabConditioning();
  el.hass = fakeHass;
  el.data = { ...baseData }; // simulated coordinator tick #1

  const instanceAfterFirstTick = el._shadowComparisonEl;
  assert.ok(instanceAfterFirstTick,
    'HelixTabConditioning must create and cache a comparison-chart instance on first render');

  // Simulate several further coordinator ticks in quick succession — this
  // is exactly what a real dashboard does every 30 seconds (and what a
  // burst of unrelated hass churn would do far more often).
  el.data = { ...baseData };
  el.data = { ...baseData };
  el.data = { ...baseData };

  const instanceAfterLaterTicks = el._shadowComparisonEl;
  assert.strictEqual(instanceAfterLaterTicks, instanceAfterFirstTick,
    'the SAME chart instance must be reused across coordinator ticks, never recreated — ' +
    'recreating it is exactly what caused the empty/loading flash every 30 seconds');

  // Let _fetch()'s internal await resolve before checking the call count.
  await new Promise((resolve) => setImmediate(resolve));

  assert.strictEqual(callCount, 1,
    `the chart must fetch comparison data at most once across repeated coordinator ticks ` +
    `(got ${callCount} calls) — refetching on every tick was the flicker's direct cause`);

  // Toggling Environmental Learning off then back on must not lose the
  // cached instance either (the slot disappears from the rebuilt markup,
  // but the JS reference the tab holds must survive so re-enabling doesn't
  // force a needless refetch of data that hasn't gone stale).
  el.data = { ...baseData, thermal_learning_enabled: false };
  el.data = { ...baseData, thermal_learning_enabled: true };
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(el._shadowComparisonEl, instanceAfterFirstTick,
    'the cached chart instance must survive Environmental Learning being toggled off and back on');
  assert.strictEqual(callCount, 1,
    'toggling Environmental Learning off and back on must not trigger an extra fetch');

  console.log('OK: comparison chart instance persists across coordinator ticks; fetched only once, not per-tick.');
}

main().catch((e) => { console.error(e); process.exit(1); });
