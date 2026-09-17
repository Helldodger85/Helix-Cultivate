// v1.6.0 Part 9 — confirms the Environmental Learning Settings tab renders
// the trailing-window retrospective summary as plain aggregate text (no
// <svg>/chart element — this tab's role is configuration, not ongoing
// monitoring), and is absent when there's nothing yet to summarise.
'use strict';

const assert = require('assert');
const { loadPanelModule } = require('./harness');

const { elements } = loadPanelModule();
const HelixTabSettings = elements['helix-tab-settings'];
assert.ok(HelixTabSettings, 'helix-tab-settings was not registered');

function renderWith(data, learningStatus) {
  const el = new HelixTabSettings();
  el._section = 'learning';
  el._learningStatus = learningStatus;
  el.hass = {};
  el.data = data;
  return el.shadowRoot.innerHTML;
}

// ── No summary yet: section must be absent, not an empty/placeholder chart ─
const noneHtml = renderWith(
  { entry_id: 'e1', thermal_learning_enabled: true },
  { learning_state: 'active', shadow_retrospective: null },
);
assert.ok(!noneHtml.includes('Shadow Mode — Last'),
  'Retrospective summary card must not render when there is nothing to summarise yet');

// ── With a summary: renders the aggregate text, not a graph ────────────────
const withHtml = renderWith(
  { entry_id: 'e1', thermal_learning_enabled: true },
  {
    learning_state: 'active',
    shadow_retrospective: {
      trailing_days: 7, agreement_pct: 82.5, avg_disagreement_bias_c: 1.4, sample_count: 120,
    },
  },
);
assert.ok(withHtml.includes('Shadow Mode — Last 7 Days'),
  'Retrospective summary card title missing');
assert.ok(withHtml.includes('agreed on') && withHtml.includes('82.5%'),
  'Retrospective summary must state the agreement percentage');
assert.ok(withHtml.includes('1.4') && withHtml.includes('disagreed'),
  'Retrospective summary must state the average disagreement bias');
assert.ok(!withHtml.includes('<svg'),
  'Retrospective summary must be plain text, not a live graph/chart');

console.log('OK: Settings tab retrospective summary renders as plain aggregate text, never a graph.');
