// v1.5.2 Part 1 — confirms the Plant Cycle tab (<helix-tab-cycle>) no
// longer gates the entire Grow Stage Timeline/Profile Card editor behind
// cycle_state === 'active'. Instantiates the real, shipped custom element
// (via tests/js/harness.js's dependency-free sandbox) with both
// cycle_state values and inspects the resulting shadowRoot.innerHTML.
'use strict';

const assert = require('assert');
const { loadPanelModule } = require('./harness');

const { elements } = loadPanelModule();
const HelixTabCycle = elements['helix-tab-cycle'];
assert.ok(HelixTabCycle, 'helix-tab-cycle was not registered — was the tag name changed?');

function renderWith(data) {
  const el = new HelixTabCycle();
  el.hass = {};
  el.data = data; // triggers _render() via the `set data(d)` setter
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
};

// ── not_started: full timeline/profile editor must still be present ────────
const notStartedHtml = renderWith({ ...baseData, cycle_state: 'not_started' });

assert.ok(notStartedHtml.includes('No Active Cycle'), 'not_started: status panel (Start form) missing');
assert.ok(notStartedHtml.includes('id="submit-start-cycle-btn"'), 'not_started: Start New Cycle button missing');
assert.ok(notStartedHtml.includes('Grow Stage Timeline'), 'not_started: Grow Stage Timeline heading missing — timeline must always be visible');
assert.ok(notStartedHtml.includes('data-stage="germination"'), 'not_started: stage timeline items missing');
assert.ok(notStartedHtml.includes('id="vpd-min-slider"'), 'not_started: VPD range slider missing — stage profile must be editable');
assert.ok(notStartedHtml.includes('id="temp-anchor-slider"'), 'not_started: Temperature anchor slider missing');
assert.ok(notStartedHtml.includes('id="light-slider"'), 'not_started: Light Intensity slider missing');
assert.ok(notStartedHtml.includes('id="fan-slider"'), 'not_started: Fan Speed slider missing');
assert.ok(notStartedHtml.includes('id="stage-duration-slider"'), 'not_started: Stage Duration slider missing (v1.5.0 Part 3)');
assert.ok(notStartedHtml.includes('id="save-stage-targets-btn"'), 'not_started: Save Stage Targets button missing');
assert.ok(notStartedHtml.includes('Growth Mode'), 'not_started: Growth Mode section missing');
assert.ok(!notStartedHtml.includes('⚠ Abort Cycle'), 'not_started: Abort Cycle must not appear — no cycle exists yet');

// Status panel must render BEFORE the Grow Stage Timeline, never after.
const noActiveIdx = notStartedHtml.indexOf('No Active Cycle');
const timelineIdx = notStartedHtml.indexOf('Grow Stage Timeline');
assert.ok(noActiveIdx >= 0 && timelineIdx >= 0 && noActiveIdx < timelineIdx,
  'not_started: status panel must render above the Grow Stage Timeline');

// ── active: status panel switches to Day X/Y + Abort Cycle, timeline stays ──
const activeHtml = renderWith({ ...baseData, cycle_state: 'active' });

// (Note: the Abort Cycle card's own description text legitimately mentions
// the phrase "No Active Cycle" in passing — check for the Start form's own
// submit button instead, which only ever appears in the not_started panel.)
assert.ok(!activeHtml.includes('id="submit-start-cycle-btn"'), 'active: the not_started status panel (Start form) must not appear');
assert.ok(activeHtml.includes('Day 5 / 14'), 'active: Day X/Y progress display missing');
assert.ok(activeHtml.includes('⚠ Abort Cycle'), 'active: Abort Cycle control missing');
assert.ok(activeHtml.includes('Grow Stage Timeline'), 'active: Grow Stage Timeline heading missing');
assert.ok(activeHtml.includes('id="vpd-min-slider"'), 'active: VPD range slider missing');
assert.ok(activeHtml.includes('id="stage-duration-slider"'), 'active: Stage Duration slider missing');

const dayProgressIdx = activeHtml.indexOf('Day 5 / 14');
const activeTimelineIdx = activeHtml.indexOf('Grow Stage Timeline');
assert.ok(dayProgressIdx >= 0 && activeTimelineIdx >= 0 && dayProgressIdx < activeTimelineIdx,
  'active: status panel (Day X/Y + Abort Cycle) must render above the Grow Stage Timeline');

// ── Growth Mode lock behavior unaffected by this fix (Part 1.3) ────────────
const unoccupiedHtml = renderWith({ ...baseData, cycle_state: 'not_started', zone2_occupied: false });
const occupiedHtml = renderWith({ ...baseData, cycle_state: 'active', zone2_occupied: true });

assert.ok(!unoccupiedHtml.includes('cycle-growth-mode-btn') || !/cycle-growth-mode-btn[^>]*disabled/.test(unoccupiedHtml),
  'Growth Mode must be editable (not disabled) while unoccupied');
assert.ok(/cycle-growth-mode-btn[^>]*disabled/.test(occupiedHtml) || /disabled[^>]*cycle-growth-mode-btn/.test(occupiedHtml),
  'Growth Mode must be locked (disabled) while zone2_occupied is True');

console.log('OK: Plant Cycle status panel and Grow Stage Timeline are correctly split and always-visible/editable.');
