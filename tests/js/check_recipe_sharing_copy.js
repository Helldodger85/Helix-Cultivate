// v1.6.0 Part 4 — confirms the Recipe Sharing card carries honest
// explanatory copy about its real scope: export/import operates on the
// ENTIRE grow plan (all stages) as one file, not a single stage, and there
// is no built-in database/directory/strain-lookup feature.
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
};

const html = renderWith(baseData);
const normalized = html.replace(/\s+/g, ' ');

assert.ok(normalized.includes('entire grow plan'),
  'Recipe Sharing copy must clarify it covers the entire grow plan, not a single stage');
assert.ok(normalized.includes('every stage'),
  'Recipe Sharing copy must clarify every stage is included');
assert.ok(normalized.includes('no built-in database, directory, or automated strain-lookup feature'),
  'Recipe Sharing copy must honestly disclaim any database/directory/strain-lookup feature');

// Must render inside the same card as the Export/Import buttons, not a
// stray disconnected block.
const cardTitleIdx = html.indexOf('📋 Recipe Sharing');
const copyIdx = normalized.indexOf('entire grow plan');
const exportBtnIdx = html.indexOf('id="export-recipe-btn"');
assert.ok(cardTitleIdx >= 0 && copyIdx >= 0 && exportBtnIdx > 0,
  'Recipe Sharing card, copy, and Export button must all be present');

console.log('OK: Recipe Sharing copy accurately reflects whole-grow-plan export/import scope.');
