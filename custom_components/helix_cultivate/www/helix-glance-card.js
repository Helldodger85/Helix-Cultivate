/**
 * Helix Cultivate — Glance Card v1.0.0
 *
 * Standalone Lovelace custom card. Zero dependency on helix-panel.js (no
 * module system available in the Lovelace resource-loading context), so all
 * shared helpers (state readers, formatters, sparkline renderer) are
 * duplicated verbatim below.
 *
 * Usage in a Lovelace dashboard (YAML mode):
 *   type: custom:helix-glance-card
 *   entity_prefix: sensor.helix_cultivate   # optional, this is the default
 */

// ─────────────────────────────────────────────────────────────────────────────
// Helpers (duplicated from helix-panel.js — no module system in Lovelace)
// ─────────────────────────────────────────────────────────────────────────────

function _state(hass, entityId) {
  if (!hass || !entityId) return null;
  const s = hass.states[entityId];
  return s ? s.state : null;
}

function _attr(hass, entityId, attr) {
  if (!hass || !entityId) return null;
  const s = hass.states[entityId];
  return s ? (s.attributes[attr] ?? null) : null;
}

function _numState(hass, entityId) {
  const v = _state(hass, entityId);
  if (v === null || v === 'unavailable' || v === 'unknown') return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

function fn(v, d = 1, fb = '—') {
  if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return fb;
  return Number(v).toFixed(d);
}
function fT(v) { return v != null ? `${fn(v, 1)}°C` : '—'; }
function fRH(v) { return v != null ? `${fn(v, 0)}%` : '—'; }
function fVPD(v) { return v != null ? `${fn(v, 2)} kPa` : '—'; }

function vpdColour(vpd, target) {
  if (vpd == null || target == null) return 'var(--secondary-text-color,#9a9ab0)';
  const d = Math.abs(vpd - target);
  if (d < 0.08) return '#48c78e';
  if (d < 0.20) return '#ffb700';
  return '#ff5252';
}

const STAGE_LABELS = {
  germination:  { icon: '🌱', label: 'Germination' },
  seedling:     { icon: '🌿', label: 'Seedling' },
  early_veg:    { icon: '🌳', label: 'Early Veg' },
  late_veg:     { icon: '🌳', label: 'Late Veg' },
  stretch:      { icon: '📏', label: 'Stretch' },
  peak_flower:  { icon: '🌸', label: 'Peak Flower' },
  ripening:     { icon: '🍯', label: 'Ripening' },
  drying:       { icon: '🍃', label: 'Drying' },
};

// ── Sparkline renderer (Option A — duplicated verbatim from helix-panel.js's
//    buildSparklineSVG, with the Phase 10D band-overlay extension) ───────────
function buildSparklineSVG(points, colour, width = 200, height = 40, filled = false, band = null) {
  if (!points || points.length < 2) {
    return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
      <text x="${width/2}" y="${height/2}" text-anchor="middle" font-size="9"
        fill="rgba(150,160,180,0.5)">No data</text></svg>`;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const pad = 4;
  const w = width - pad * 2;
  const h = height - pad * 2;

  const toY = (v) => pad + h - ((v - min) / range) * h;

  const pts = points.map((v, i) => {
    const x = pad + (i / (points.length - 1)) * w;
    const y = toY(v);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const polyline = pts.join(' ');
  const firstPt = pts[0];
  const lastPt = pts[pts.length - 1];

  const fillPath = filled
    ? `<polygon points="${firstPt} ${polyline} ${lastPt.split(',')[0]},${pad + h} ${pad},${pad + h}"
        fill="${colour}" opacity="0.12"/>`
    : '';

  let bandRect = '';
  if (band && typeof band.min === 'number' && typeof band.max === 'number' && points.length > 1) {
    const yMin = toY(band.max);
    const yMax = toY(band.min);
    bandRect = `<rect x="0" y="${yMin.toFixed(1)}" width="${width}" height="${Math.max(0, yMax - yMin).toFixed(1)}"
        fill="var(--hx-accent, #6abf69)" fill-opacity="0.13" rx="2"/>`;
  }

  const lastX = parseFloat(lastPt.split(',')[0]);
  const lastY = parseFloat(lastPt.split(',')[1]);

  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="overflow:visible">
    ${bandRect}
    ${fillPath}
    <polyline points="${polyline}" fill="none" stroke="${colour}" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${lastX}" cy="${lastY}" r="3" fill="${colour}"/>
  </svg>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// <helix-glance-card>
// ─────────────────────────────────────────────────────────────────────────────

class HelixGlanceCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._entityPrefix = 'sensor.helix_cultivate';
  }

  setConfig(config) {
    this._config = config || {};
    this._entityPrefix = this._config.entity_prefix || 'sensor.helix_cultivate';
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 2;
  }

  _eid(suffix) {
    return `${this._entityPrefix}_${suffix}`;
  }

  _render() {
    if (!this._hass) return;
    const hass = this._hass;

    const stageSlug = _state(hass, this._eid('grow_stage')) || 'germination';
    const stageMeta = STAGE_LABELS[stageSlug] || STAGE_LABELS.germination;
    const stageDay = _numState(hass, this._eid('stage_day'));
    const stageDuration = _attr(hass, this._eid('grow_stage'), 'stage_duration');

    const vpd = _numState(hass, this._eid('leaf_vpd'));
    const vpdTarget = _attr(hass, this._eid('leaf_vpd'), 'vpd_target_kpa') ?? 1.0;
    const vpdMin = _attr(hass, this._eid('leaf_vpd'), 'vpd_target_min');
    const vpdMax = _attr(hass, this._eid('leaf_vpd'), 'vpd_target_max');

    const temp = _numState(hass, this._eid('upper_canopy_temp'));
    const rh = _numState(hass, this._eid('upper_canopy_rh'));

    const vCol = vpdColour(vpd, vpdTarget);
    const band = (typeof vpdMin === 'number' && typeof vpdMax === 'number')
      ? { min: vpdMin, max: vpdMax }
      : null;
    // Glance card has no history API access — render the current reading as
    // a two-point flat line so the band overlay + marker dot still draw.
    const sparkPoints = vpd != null ? [vpd, vpd] : [];
    const spark = buildSparklineSVG(sparkPoints, vCol, 160, 32, false, band);

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          --hx-card: var(--card-background-color, #1c1f26);
          --hx-text: var(--primary-text-color, #fff);
          --hx-text2: var(--secondary-text-color, #9aa4b2);
          --hx-border: var(--divider-color, #2a2f3a);
          --hx-accent: var(--primary-color, #6abf69);
        }
        ha-card {
          background: var(--hx-card);
          padding: 12px 16px;
          border-radius: var(--ha-card-border-radius, 12px);
        }
        .hx-glance-head {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 8px;
        }
        .hx-glance-stage {
          font-size: .95rem; font-weight: 700; color: var(--hx-text);
          display: flex; align-items: center; gap: 6px;
        }
        .hx-glance-day {
          font-size: .72rem; color: var(--hx-text2);
        }
        .hx-glance-vpd-row {
          display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
        }
        .hx-glance-vpd-val {
          font-size: 1.1rem; font-weight: 800;
        }
        .hx-glance-chips {
          display: flex; gap: 14px; font-size: .8rem; color: var(--hx-text2);
        }
        .hx-glance-chip b { color: var(--hx-text); font-weight: 700; }
      </style>
      <ha-card>
        <div class="hx-glance-head">
          <span class="hx-glance-stage">${stageMeta.icon} ${stageMeta.label}</span>
          <span class="hx-glance-day">${stageDay != null ? `Day ${stageDay}` : ''}${stageDuration != null ? ` / ${stageDuration}` : ''}</span>
        </div>
        <div class="hx-glance-vpd-row">
          ${spark}
          <span class="hx-glance-vpd-val" style="color:${vCol}">${fVPD(vpd)}</span>
        </div>
        <div class="hx-glance-chips">
          <span class="hx-glance-chip">🌡 <b>${fT(temp)}</b></span>
          <span class="hx-glance-chip">💧 <b>${fRH(rh)}</b></span>
        </div>
      </ha-card>
    `;
  }
}

customElements.define('helix-glance-card', HelixGlanceCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'helix-glance-card',
  name: 'Helix Cultivate Glance',
  description: 'Compact stage + VPD + climate summary for Lovelace dashboards.',
  preview: false,
});
