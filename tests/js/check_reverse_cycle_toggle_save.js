// v1.6.1 Part 2 — regression test for the Conditioning Room hardware-
// mapping form's Reverse Cycle Unit toggle not persisting.
//
// Root cause (confirmed by reading the real code, not assumed): of the
// three possible failure points named in the ticket —
//   1. the frontend's Save payload never containing the field,
//   2. the backend silently failing to persist it, or
//   3. the frontend reading the wrong value back on reopen —
// only #1 was real. HelixTabConditioning's extraFieldsGetter callback
// (passed to _bindHwPicker) read only `#hw-preheat-lead-slider` — it never
// looped over `.hw-layer-toggle` checkboxes at all, unlike the equivalent
// callbacks in HelixTabGrowspace and HelixTabDrying, which both already
// do `shadowRoot.querySelectorAll('.hw-layer-toggle').forEach(el => {
// fields[el.dataset.layer] = el.checked; })`. So Save's WS payload to
// `helix_cultivate/update_settings_fields` never contained
// `zone1_is_reverse_cycle` at all, regardless of the checkbox's state.
// `zone1_is_reverse_cycle` was already correctly in the backend's
// VALID_SETTINGS_FIELD_KEYS allowlist and its debounced option-write flush
// already merges against the config entry's live options (see
// tests/test_v161_part2_reverse_cycle_persistence.py for that backend
// proof) — so checkpoints #2 and #3 were never the problem.
//
// The harness's fake shadow root can't parse real HTML/DOM (see
// harness.js's own header comment), so this test captures the actual
// extraFieldsGetter closure HelixTabConditioning._render() passes to
// _bindHwPicker (by temporarily stubbing the module's real _bindHwPicker
// to record it) and invokes that real closure against a purpose-built
// fake shadowRoot standing in for a checked/unchecked toggle — exercising
// the exact shipped logic, not a re-implementation of it.
'use strict';

const assert = require('assert');
const { loadPanelModule } = require('./harness');

function captureExtraFieldsGetter(zone1IsReverseCycleChecked) {
  const { context, elements } = loadPanelModule();
  const HelixTabConditioning = elements['helix-tab-conditioning'];
  assert.ok(HelixTabConditioning, 'helix-tab-conditioning was not registered');

  let capturedGetter = null;
  context._bindHwPicker = (_shadowRoot, _hostEl, _hwKeys, extraFieldsGetter) => {
    capturedGetter = extraFieldsGetter;
  };

  const el = new HelixTabConditioning();
  el._isEditingHardware = true;
  el.hass = {};
  el.data = { entry_id: 'e1', zone1_name: 'Conditioning Room', hw_map: {} };

  assert.ok(capturedGetter, 'HelixTabConditioning must pass an extraFieldsGetter to _bindHwPicker');

  // Stand in for the real DOM the harness can't parse: only
  // '.hw-layer-toggle' resolves to anything, matching what the getter
  // actually queries for.
  el.shadowRoot.querySelectorAll = (selector) => {
    if (selector === '.hw-layer-toggle') {
      return [{ dataset: { layer: 'zone1_is_reverse_cycle' }, checked: zone1IsReverseCycleChecked }];
    }
    return [];
  };
  el.shadowRoot.querySelector = () => null; // no preheat slider present in this test

  return capturedGetter();
}

// ── Toggle ON: the save payload must contain it as true ────────────────────
const fieldsOn = captureExtraFieldsGetter(true);
assert.strictEqual(fieldsOn.zone1_is_reverse_cycle, true,
  'Save payload must include zone1_is_reverse_cycle: true when the checkbox is checked');

// ── Toggle OFF: the save payload must contain it as false, not omit it ─────
const fieldsOff = captureExtraFieldsGetter(false);
assert.strictEqual(fieldsOff.zone1_is_reverse_cycle, false,
  'Save payload must include zone1_is_reverse_cycle: false when the checkbox is unchecked');

console.log('OK: Conditioning Room hardware form now includes the Reverse Cycle Unit toggle in its save payload.');
