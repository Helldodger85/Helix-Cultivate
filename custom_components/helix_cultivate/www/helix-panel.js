/**
 * Helix Cultivate — LitElement Dashboard Panel v2.0.0
 *
 * Architecture:
 *   <helix-panel>            Root orchestrator — tab router, hass bridge, theme engine
 *     <helix-tab-bar>        Dynamic navigation tabs (visibility tied to module flags)
 *     <helix-tab-telemetry>  VPD HUD, DLI, ambient bar, zone glance cards + sparklines
 *     <helix-tab-cycle>      Plant Cycle Engine — stage timeline, VPD/light curves
 *     <helix-tab-growspace>  Primary Grow Space — sensors, appliances, fan matrix
 *     <helix-tab-conditioning> Conditioning Room — sensors, HVAC, humidity
 *     <helix-tab-drying>     Drying Environment — 60/60 profile status & hardware
 *     <helix-tab-settings>   Settings Hub — module registry, calibration, safety
 *
 * Data visualisation: native SVG sparklines via HA recorder/statistics_during_period
 * WebSocket. Zero external CDN dependencies. Zero iframes.
 *
 * Theme: Dark/Light toggle persisted to localStorage.
 * Zero-Ghost: unmapped entity badges are hidden automatically.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
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

function _swOn(hass, entityId) {
  return _state(hass, entityId) === 'on';
}

// Escape free-text before interpolating it into an innerHTML template
// literal. Journal/IPM entries (label, note, etc.) come from plain <input>
// fields typed by whoever has access to the panel — without this, a
// crafted value (e.g. "<img src=x onerror=...>") is stored verbatim and
// executes for every future viewer of the tab that renders it back.
function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function fn(v, d = 1, fb = '—') {
  if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return fb;
  return Number(v).toFixed(d);
}
function fT(v) { return v != null ? `${fn(v, 1)}°C` : '—'; }
function fRH(v) { return v != null ? `${fn(v, 0)}%` : '—'; }
function fVPD(v) { return v != null ? `${fn(v, 2)} kPa` : '—'; }
function fPct(v) { return v != null ? `${fn(v, 0)}%` : '—'; }

const OVERRIDE_BADGE = '<span style="font-size:.68rem;color:var(--hx-amber);white-space:nowrap">🔧 Temporary override — reverts at next stage change</span>';

// v1.5.1: the Temporary Override section's three slider rows, pulled into
// their own pure function so this exact behavior — Light Intensity's
// slider entirely absent (not merely disabled) for the Night context,
// since it has no live effect there (the grow light is forced off outside
// its scheduled on-window regardless of ceiling/override) — is directly
// testable without needing a full DOM/custom-element harness. Temp
// Setpoint and VPD Target are unaffected: both remain fully available and
// meaningful in either context.
function _renderOverrideSlidersHtml(
  overrideCtx, tempSP, vpdT, lightP, overrideTempActive, overrideVpdActive, overrideLightActive
) {
  const lightBlock = overrideCtx === 'day' ? `
        <div class="slider-row">
          <span class="slider-lbl">Light Intensity</span>
          <input type="range" id="override-light-sl" min="0" max="100" step="1" value="${fn(overrideLightActive ?? lightP, 0)}"/>
          <span class="slider-val" id="override-light-val">${fPct(overrideLightActive ?? lightP)}</span>
        </div>
        ${overrideLightActive != null ? `<div style="margin:-6px 0 8px">${OVERRIDE_BADGE}</div>` : ''}` : '';
  return `
        <div class="slider-row">
          <span class="slider-lbl">Temp Setpoint</span>
          <input type="range" id="override-temp-sl" min="15" max="35" step="0.5" value="${fn(overrideTempActive ?? tempSP, 1)}"/>
          <span class="slider-val" id="override-temp-val">${fT(overrideTempActive ?? tempSP)}</span>
        </div>
        ${overrideTempActive != null ? `<div style="margin:-6px 0 8px">${OVERRIDE_BADGE}</div>` : ''}
        <div class="slider-row">
          <span class="slider-lbl">VPD Target</span>
          <input type="range" id="override-vpd-sl" min="0.3" max="2.0" step="0.05" value="${fn(overrideVpdActive ?? vpdT, 2)}"/>
          <span class="slider-val" id="override-vpd-val">${fVPD(overrideVpdActive ?? vpdT)}</span>
        </div>
        ${overrideVpdActive != null ? `<div style="margin:-6px 0 8px">${OVERRIDE_BADGE}</div>` : ''}
        ${lightBlock}`;
}

// Mirrors coordinator.py's midnight-safe schedule math — used only for the
// read-only "Lights on HH:MM -> off HH:MM" preview; the coordinator is the
// actual authority on the applied schedule.
function _deriveOffTime(onTimeStr, hours) {
  const parts = String(onTimeStr || '06:00').split(':');
  const onMinutes = (parseInt(parts[0], 10) || 0) * 60 + (parseInt(parts[1], 10) || 0);
  const totalMinutes = ((onMinutes + Math.round(Number(hours) * 60)) % (24 * 60) + 24 * 60) % (24 * 60);
  const oh = String(Math.floor(totalMinutes / 60)).padStart(2, '0');
  const om = String(totalMinutes % 60).padStart(2, '0');
  return `${oh}:${om}`;
}

function vpdColour(vpd, target) {
  if (vpd == null || target == null) return 'var(--secondary-text-color,#9a9ab0)';
  const d = Math.abs(vpd - target);
  if (d < 0.08) return '#48c78e';
  if (d < 0.20) return '#ffb700';
  return '#ff5252';
}

function vpdBand(vpd) {
  if (vpd == null) return '—';
  if (vpd < 0.4) return 'Propagation';
  if (vpd < 0.8) return 'Seedling';
  if (vpd < 1.2) return 'Veg';
  if (vpd < 1.6) return 'Flower';
  return 'Stress';
}

// ─────────────────────────────────────────────────────────────────────────────
// Theme CSS — supports --hx-* custom properties for dark/light modes
// ─────────────────────────────────────────────────────────────────────────────

const THEME_DARK = `
  --hx-bg:          #0f0f17;
  --hx-surface:     #1a1a2e;
  --hx-surface2:    #16213e;
  --hx-card:        #1e1e2e;
  --hx-border:      rgba(255,255,255,0.07);
  --hx-text:        #e2e8f0;
  --hx-text2:       #8892a4;
  --hx-accent:      #7c6dfa;
  --hx-green:       #48c78e;
  --hx-amber:       #ffb700;
  --hx-red:         #ff5252;
  --hx-blue:        #209cee;
  --hx-purple:      #a64dff;
  --hx-shadow:      0 4px 20px rgba(0,0,0,0.6);
`;

const THEME_LIGHT = `
  --hx-bg:          #f0f4f8;
  --hx-surface:     #ffffff;
  --hx-surface2:    #e8edf3;
  --hx-card:        #ffffff;
  --hx-border:      rgba(0,0,0,0.08);
  --hx-text:        #1a202c;
  --hx-text2:       #718096;
  --hx-accent:      #5a4fcf;
  --hx-green:       #38a169;
  --hx-amber:       #d97706;
  --hx-red:         #e53e3e;
  --hx-blue:        #2b6cb0;
  --hx-purple:      #805ad5;
  --hx-shadow:      0 2px 8px rgba(0,0,0,0.12);
`;

const BASE_CSS = `
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :host {
    display: block;
    font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
    color: var(--hx-text);
    background: var(--hx-bg);
    min-height: 100vh;
  }
  .panel-wrap {
    max-width: 1100px;
    margin: 0 auto;
    padding: 16px 12px 40px;
  }
  /* ── Cards ── */
  .card {
    background: var(--hx-card);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 12px;
    box-shadow: var(--hx-shadow);
    border: 1px solid var(--hx-border);
  }
  .card-sm { padding: 12px; border-radius: 10px; }
  .card-title {
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--hx-text2);
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  /* ── Badges ── */
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 3px 8px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
    white-space: nowrap;
  }
  .bg-green  { background: rgba(72,199,142,0.15);  color: var(--hx-green); }
  .bg-amber  { background: rgba(255,183,0,0.15);   color: var(--hx-amber); }
  .bg-red    { background: rgba(255,82,82,0.15);   color: var(--hx-red); }
  .bg-blue   { background: rgba(32,156,238,0.15);  color: var(--hx-blue); }
  .bg-purple { background: rgba(166,77,255,0.15);  color: var(--hx-purple); }
  .bg-gray   { background: rgba(150,160,180,0.12); color: var(--hx-text2); }
  .bg-accent { background: rgba(124,109,250,0.15); color: var(--hx-accent); }
  /* ── Metrics ── */
  .metric-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 5px 0;
    border-bottom: 1px solid var(--hx-border);
    font-size: 0.85rem;
  }
  .metric-row:last-child { border-bottom: none; }
  .metric-label { color: var(--hx-text2); font-size: 0.8rem; }
  .metric-val   { font-weight: 600; }
  /* ── Grids ── */
  .g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .g3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
  .g4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; }
  @media (max-width: 640px) {
    .g2 { grid-template-columns: 1fr 1fr; }
    .g3 { grid-template-columns: 1fr 1fr; }
    .g4 { grid-template-columns: 1fr 1fr; }
  }
  /* ── Mini stat cell ── */
  .stat-cell {
    background: var(--hx-surface2);
    border-radius: 10px;
    padding: 10px 8px;
    text-align: center;
  }
  .stat-cell .val { font-size: 1.05rem; font-weight: 700; }
  .stat-cell .lbl { font-size: 0.68rem; color: var(--hx-text2); margin-top: 2px; }
  .stat-cell.disabled { opacity: 0.4; }
  .stat-cell.disabled .val { color: var(--hx-text2); }
  /* ── Sliders ── */
  .slider-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
  .slider-lbl { font-size: 0.78rem; color: var(--hx-text2); min-width: 130px; }
  .slider-val { font-size: 0.82rem; font-weight: 600; min-width: 48px; text-align: right; }
  input[type=range] {
    -webkit-appearance: none; flex: 1; height: 4px;
    border-radius: 2px; background: var(--hx-border);
    outline: none; cursor: pointer;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 16px; height: 16px;
    border-radius: 50%; background: var(--hx-accent); cursor: pointer;
  }
  /* ── Toggle switch ── */
  .toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 6px 0; }
  .toggle-lbl { font-size: 0.85rem; }
  label.sw { position: relative; display: inline-block; width: 42px; height: 24px; cursor: pointer; }
  label.sw input { opacity: 0; width: 0; height: 0; }
  .sw-track {
    position: absolute; top:0; left:0; right:0; bottom:0;
    border-radius: 12px; background: var(--hx-border); transition: background .2s;
  }
  label.sw input:checked + .sw-track { background: var(--hx-accent); }
  .sw-thumb {
    position: absolute; height: 18px; width: 18px;
    left: 3px; top: 3px; border-radius: 50%;
    background: #fff; transition: transform .2s;
    pointer-events: none;
  }
  label.sw input:checked ~ .sw-thumb { transform: translateX(18px); }
  /* ── Override tristate buttons ── */
  .tristate { display: flex; gap: 2px; }
  .tristate button {
    flex: 1; padding: 4px 6px; font-size: 0.72rem; font-weight: 600;
    border: 1px solid var(--hx-border); background: var(--hx-surface2);
    color: var(--hx-text2); cursor: pointer; border-radius: 6px;
    transition: background .15s, color .15s;
  }
  .tristate button.active { background: var(--hx-accent); color: #fff; border-color: var(--hx-accent); }
  /* ── Number input ── */
  input[type=number] {
    background: var(--hx-surface2); border: 1px solid var(--hx-border);
    color: var(--hx-text); border-radius: 6px; padding: 4px 8px;
    font-size: 0.85rem; width: 72px; text-align: center;
  }
  /* ── Divider ── */
  hr { border: none; border-top: 1px solid var(--hx-border); margin: 10px 0; }
  /* ── Chip row ── */
  .chip-row { display: flex; gap: 6px; flex-wrap: wrap; }
  /* ── Section header ── */
  .sec { font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--hx-text2); margin: 14px 0 6px; }
`;

// ─────────────────────────────────────────────────────────────────────────────
// SVG Sparkline Builder (pure native — no external deps)
// ─────────────────────────────────────────────────────────────────────────────

function buildSparklineSVG(points, colour, width = 200, height = 40, filled = false, band = null) {
  if (!points || points.length < 2) {
    return `<svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <text x="${width/2}" y="${height/2}" text-anchor="middle" font-size="9"
        fill="rgba(150,160,180,0.5)">No data</text></svg>`;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const pad = 4;
  const w = width - pad * 2;
  const h = height - pad * 2;

  // Same linear-scale mapping used for the trace points — reused for the
  // optional target-range band so the band sits in the identical coordinate
  // space as the polyline itself.
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
    // SVG y-axis is inverted — a higher kPa value maps to a lower y coordinate.
    const yMin = toY(band.max);
    const yMax = toY(band.min);
    bandRect = `<rect x="0" y="${yMin.toFixed(1)}" width="${width}" height="${Math.max(0, yMax - yMin).toFixed(1)}"
        fill="var(--hx-accent, #6abf69)" fill-opacity="0.13" rx="2"/>`;
  }

  const lastX = parseFloat(lastPt.split(',')[0]);
  const lastY = parseFloat(lastPt.split(',')[1]);

  // Part 1.3: width="100%" + preserveAspectRatio="none" so the sparkline
  // genuinely fills its container's actual measured width — the previous
  // fixed pixel width attribute rendered at a constant size regardless of
  // how much space the card actually had. The viewBox keeps all the point
  // math above in a fixed logical coordinate space; only the final render
  // size is now responsive.
  return `<svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="overflow:visible;display:block">
    ${bandRect}
    ${fillPath}
    <polyline points="${polyline}" fill="none" stroke="${colour}" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
    <circle cx="${lastX}" cy="${lastY}" r="3" fill="${colour}" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// VPD Radial Gauge  <helix-vpd-gauge>
// ─────────────────────────────────────────────────────────────────────────────

class HelixVpdGauge extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); }
  set vpd(v) { this._vpd = v; this._render(); }
  set target(v) { this._target = v; this._render(); }

  _render() {
    const vpd = this._vpd ?? null;
    const target = this._target ?? 1.0;
    const max = 2.0;
    const pct = vpd !== null ? Math.min(1, Math.max(0, vpd / max)) : 0;
    const r = 52, cx = 64, cy = 64, start = 210, sweep = 300;

    function arc(r, a0, a1, sw) {
      const toRad = a => (a * Math.PI) / 180;
      const sx = cx + r * Math.cos(toRad(a0));
      const sy = cy + r * Math.sin(toRad(a0));
      const ex = cx + r * Math.cos(toRad(a1));
      const ey = cy + r * Math.sin(toRad(a1));
      return `M ${sx.toFixed(2)} ${sy.toFixed(2)} A ${r} ${r} 0 ${sw > 180 ? 1 : 0} 1 ${ex.toFixed(2)} ${ey.toFixed(2)}`;
    }

    const track = arc(r, start, start + sweep, sweep);
    const value = arc(r, start, start + sweep * pct, sweep * pct);
    const col = vpdColour(vpd, target);

    this.shadowRoot.innerHTML = `
      <style>:host{display:inline-block;} svg{overflow:visible;}
        .gc{text-anchor:middle;dominant-baseline:middle;}</style>
      <svg width="128" height="128" viewBox="0 0 128 128">
        <path d="${track}" fill="none" stroke="rgba(150,160,180,0.12)" stroke-width="10" stroke-linecap="round"/>
        <path d="${value}" fill="none" stroke="${col}" stroke-width="10" stroke-linecap="round"
          style="transition:d .5s ease,stroke .5s ease;"/>
        <text x="64" y="54" class="gc" font-size="20" font-weight="800" fill="${col}">
          ${vpd !== null ? fn(vpd, 2) : '—'}</text>
        <text x="64" y="73" class="gc" font-size="10" fill="rgba(150,160,180,0.5)">kPa VPD</text>
        <text x="64" y="89" class="gc" font-size="9" fill="rgba(150,160,180,0.35)">
          tgt ${fn(target, 2)}</text>
        <text x="64" y="104" class="gc" font-size="8" fill="${col}" opacity="0.7">
          ${vpdBand(vpd)}</text>
      </svg>`;
  }
  connectedCallback() { this._render(); }
}
customElements.define('helix-vpd-gauge', HelixVpdGauge);

// ─────────────────────────────────────────────────────────────────────────────
// DLI Arc Tracker  <helix-dli-tracker>
// ─────────────────────────────────────────────────────────────────────────────

class HelixDliTracker extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); }
  set dli(v) { this._dli = v; this._render(); }
  set target(v) { this._target = v; this._render(); }

  _render() {
    const dli = this._dli ?? null;
    const target = this._target ?? 40;
    const pct = dli !== null ? Math.min(1, Math.max(0, dli / target)) : 0;
    const circ = 201;

    this.shadowRoot.innerHTML = `
      <style>:host{display:flex;flex-direction:column;align-items:center;}
        .w{position:relative;width:84px;height:84px;}
        svg{position:absolute;top:0;left:0;}
        .ct{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;}
        .v{font-size:.9rem;font-weight:800;color:#209cee;}
        .u{font-size:.6rem;color:rgba(150,160,180,.5);}
      </style>
      <div class="w">
        <svg width="84" height="84" viewBox="0 0 84 84">
          <circle cx="42" cy="42" r="32" fill="none" stroke="rgba(150,160,180,0.1)" stroke-width="7"/>
          <circle cx="42" cy="42" r="32" fill="none" stroke="#209cee" stroke-width="7"
            stroke-dasharray="${Math.round(pct*circ)} ${circ}"
            stroke-dashoffset="50" stroke-linecap="round"
            style="transition:stroke-dasharray .6s ease;"/>
        </svg>
        <div class="ct">
          <div class="v">${dli !== null ? fn(dli, 1) : '—'}</div>
          <div class="u">DLI</div>
        </div>
      </div>`;
  }
  connectedCallback() { this._render(); }
}
customElements.define('helix-dli-tracker', HelixDliTracker);

// ─────────────────────────────────────────────────────────────────────────────
// Sparkline Card  <helix-sparkline-card>
// Queries HA recorder WebSocket and renders native SVG sparklines
// ─────────────────────────────────────────────────────────────────────────────

class HelixSparklineCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._timeframe = 'live'; // live | 24h | 48h | 7d
    this._data = {};
    this._sparkData = {};
    this._loading = false;
  }

  set hass(h) { this._hass = h; this._renderShell(); this._maybeFetch(); }
  set data(d) { this._data = d || {}; this._renderShell(); }
  set zone(z) { this._zone = z; }
  // Part 1.3: the parent tab rebuilds its whole innerHTML (including this
  // element's own <helix-sparkline-card> tag) on every coordinator data
  // push, which destroys and recreates this instance — silently resetting
  // _timeframe back to the constructor default ('live') every time. The
  // parent now persists the selection itself and restores it here via this
  // setter immediately after each rebuild.
  set timeframe(tf) {
    if (!tf || tf === this._timeframe) return;
    this._timeframe = tf;
    this._renderShell();
    if (this._timeframe !== 'live') this._maybeFetch();
  }
  get timeframe() { return this._timeframe; }

  _entityIds() {
    const d = this._data;
    return {
      temp:  d.temp_entity_id   || null,
      rh:    d.rh_entity_id     || null,
      vpd:   d.vpd_entity_id    || null,
    };
  }

  async _maybeFetch() {
    if (this._timeframe === 'live' || !this._hass) return;
    if (this._loading) return;
    const ids = this._entityIds();
    const statIds = Object.values(ids).filter(Boolean);
    if (!statIds.length) return;

    const now = new Date();
    const hoursMap = { '24h': 24, '48h': 48, '7d': 168 };
    const hours = hoursMap[this._timeframe] || 24;
    const start = new Date(now.getTime() - hours * 3600 * 1000).toISOString();

    this._loading = true;
    try {
      const result = await this._hass.callWS({
        type: 'recorder/statistics_during_period',
        start_time: start,
        end_time: now.toISOString(),
        statistic_ids: statIds,
        period: this._timeframe === '7d' ? 'hour' : '5minute',
        types: ['mean'],
      });

      const extract = (id) => {
        if (!id || !result[id]) return [];
        return result[id].map(pt => pt.mean).filter(v => v != null);
      };

      this._sparkData = {
        temp: extract(ids.temp),
        rh:   extract(ids.rh),
        vpd:  extract(ids.vpd),
      };
    } catch (e) {
      this._sparkData = {};
    } finally {
      this._loading = false;
      this._renderShell();
    }
  }

  _tfBtn(id, label) {
    const active = this._timeframe === id ? 'active' : '';
    return `<button class="tf-btn ${active}" data-tf="${id}">${label}</button>`;
  }

  _renderShell() {
    const d = this._data;
    const zone = this._zone || 'Zone';
    const ids = this._entityIds();

    // Live values
    const temp = d.temp ?? null;
    const rh   = d.rh   ?? null;
    const vpd  = d.vpd  ?? null;
    const tgt  = d.vpd_target ?? 1.0;
    const vCol = vpdColour(vpd, tgt);
    const vpdBand = (typeof d.vpd_target_min === 'number' && typeof d.vpd_target_max === 'number')
      ? { min: d.vpd_target_min, max: d.vpd_target_max }
      : null;

    // Sparkline data
    const live = this._timeframe === 'live';
    const sd = this._sparkData;

    const sparkTemp = live
      ? buildSparklineSVG(temp != null ? [temp] : [], '#ef4444', 180, 36, true)
      : buildSparklineSVG(sd.temp || [], '#ef4444', 180, 36, true);
    const sparkRH = live
      ? buildSparklineSVG(rh != null ? [rh] : [], '#209cee', 180, 36, true)
      : buildSparklineSVG(sd.rh || [], '#209cee', 180, 36, true);
    const sparkVPD = live
      ? buildSparklineSVG(vpd != null ? [vpd] : [], vCol, 180, 36, false, vpdBand)
      : buildSparklineSVG(sd.vpd || [], vCol, 180, 36, false, vpdBand);

    this.shadowRoot.innerHTML = `
      <style>
        ${BASE_CSS}
        :host { display: block; }
        .zone-card { background: var(--hx-card); border-radius: 14px; padding: 14px;
          border: 1px solid var(--hx-border); box-shadow: var(--hx-shadow); }
        .zone-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
        .zone-name { font-size: .85rem; font-weight: 700; }
        .tf-bar { display: flex; gap: 3px; }
        .tf-btn {
          padding: 3px 7px; font-size: .68rem; font-weight: 600;
          border: 1px solid var(--hx-border); background: var(--hx-surface2);
          color: var(--hx-text2); cursor: pointer; border-radius: 5px;
          transition: background .15s, color .15s;
        }
        .tf-btn.active { background: var(--hx-accent); color: #fff; border-color: var(--hx-accent); }
        .readings { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin: 8px 0; }
        .reading { text-align: center; }
        .reading .v { font-size: 1rem; font-weight: 700; }
        .reading .l { font-size: .65rem; color: var(--hx-text2); }
        .spark-section { margin-top: 4px; }
        .spark-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
        .spark-row svg { flex: 1 1 auto; min-width: 0; width: 100%; }
        .spark-lbl { font-size: .68rem; color: var(--hx-text2); min-width: 28px; flex-shrink: 0; }
        .loading { font-size: .72rem; color: var(--hx-text2); padding: 8px 0; text-align: center; }
      </style>
      <div class="zone-card">
        <div class="zone-head">
          <span class="zone-name">${zone}</span>
          <div class="tf-bar">
            ${this._tfBtn('live','Live')}
            ${this._tfBtn('24h','24h')}
            ${this._tfBtn('48h','48h')}
            ${this._tfBtn('7d','7d')}
          </div>
        </div>
        <div class="readings">
          <div class="reading">
            <div class="v" style="color:#ef4444">${fT(temp)}</div>
            <div class="l">Temp</div>
          </div>
          <div class="reading">
            <div class="v" style="color:#209cee">${fRH(rh)}</div>
            <div class="l">RH</div>
          </div>
          <div class="reading">
            ${d.vpd_no_canopy
              ? `<div class="v" style="color:var(--hx-text2)" title="No plant canopy in this zone">N/A</div>`
              : `<div class="v" style="color:${vCol}">${fVPD(vpd)}</div>`}
            <div class="l">VPD</div>
          </div>
        </div>
        ${this._loading ? '<div class="loading">Loading history…</div>' : `
        <div class="spark-section">
          <div class="spark-row"><span class="spark-lbl">°C</span>${sparkTemp}</div>
          <div class="spark-row"><span class="spark-lbl">RH</span>${sparkRH}</div>
          <div class="spark-row"><span class="spark-lbl">VPD</span>${sparkVPD}</div>
        </div>`}
      </div>`;

    // Timeframe buttons
    this.shadowRoot.querySelectorAll('.tf-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._timeframe = btn.dataset.tf;
        this._sparkData = {};
        this._renderShell();
        if (this._timeframe !== 'live') this._maybeFetch();
        // Notify the parent tab so it can persist this selection across its
        // next full re-render (see the `timeframe` setter above).
        this.dispatchEvent(new CustomEvent('sparkline-timeframe-changed', {
          bubbles: true, composed: true,
          detail: { id: this.id, timeframe: this._timeframe },
        }));
      });
    });
  }

  connectedCallback() { this._renderShell(); }
}
customElements.define('helix-sparkline-card', HelixSparklineCard);

// ─────────────────────────────────────────────────────────────────────────────
// Tab Bar  <helix-tab-bar>
// ─────────────────────────────────────────────────────────────────────────────

class HelixTabBar extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._active = 'telemetry';
    this._tabs = [];
  }

  set tabs(t) { this._tabs = t; this._render(); }
  set active(t) { this._active = t; this._render(); }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; margin-bottom: 16px; }
        .bar {
          display: flex;
          gap: 4px;
          flex-wrap: wrap;
          background: var(--hx-surface);
          border-radius: 12px;
          padding: 6px;
          border: 1px solid var(--hx-border);
          box-shadow: var(--hx-shadow);
        }
        button {
          flex: 1 1 auto;
          padding: 8px 12px;
          border: none;
          border-radius: 8px;
          font-size: .82rem;
          font-weight: 600;
          cursor: pointer;
          background: transparent;
          color: var(--hx-text2);
          transition: background .15s, color .15s;
          white-space: nowrap;
        }
        button:hover { background: var(--hx-surface2); color: var(--hx-text); }
        button.active {
          background: var(--hx-accent);
          color: #fff;
        }
      </style>
      <nav class="bar">
        ${this._tabs.map(t => `
          <button data-tab="${t.id}" class="${t.id === this._active ? 'active' : ''}">
            ${t.icon ? t.icon + ' ' : ''}${t.label}
          </button>`).join('')}
      </nav>`;

    this.shadowRoot.querySelectorAll('button[data-tab]').forEach(btn => {
      btn.addEventListener('click', () => {
        this.dispatchEvent(new CustomEvent('tab-change', {
          bubbles: true, composed: true, detail: { tab: btn.dataset.tab }
        }));
      });
    });
  }
  connectedCallback() { this._render(); }
}
customElements.define('helix-tab-bar', HelixTabBar);

// ─────────────────────────────────────────────────────────────────────────────
// Manual Override Chip  — Hand / Off / Auto tristate
// ─────────────────────────────────────────────────────────────────────────────

function overrideChip(label, entityId, currentState, hass, visible = true) {
  if (!visible || !entityId) return '';
  const isOn = currentState === 'on' || currentState === true;
  const badgeCls = isOn ? 'bg-green' : 'bg-gray';
  const icon = isOn ? '●' : '○';
  return `<span class="badge ${badgeCls}" style="cursor:default">${icon} ${label}</span>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Telemetry HUD  <helix-tab-telemetry>
// ─────────────────────────────────────────────────────────────────────────────

class HelixTabTelemetry extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    // Part 1.3: _render() rebuilds this.shadowRoot.innerHTML on every
    // coordinator data push, which destroys and recreates the child
    // <helix-sparkline-card> elements — this dict is what survives that
    // rebuild (it lives on this outer, never-destroyed host element) so
    // each card's selected timeframe can be restored after every rebuild.
    this._sparklineTimeframes = {};
    this.addEventListener('sparkline-timeframe-changed', (e) => {
      this._sparklineTimeframes[e.detail.id] = e.detail.timeframe;
    });
  }

  set hass(h) { this._hass = h; this._render(); }
  set data(d) { this._data = d; this._render(); }

  _render() {
    const h = this._hass;
    const d = this._data || {};

    // No Active Cycle (Part 1.3) — a genuinely distinct empty state, not a
    // greyed-out live view, whenever a cycle hasn't been explicitly
    // started. Replaces the entire dashboard rather than showing gauges/
    // stage timeline for what would otherwise look like a real Day-0
    // Germination cycle that was never actually begun.
    if (d.cycle_state === 'not_started') {
      this._renderNoActiveCycle();
      return;
    }

    const vpd         = d.leaf_vpd       ?? null;
    const vpdTarget   = d.vpd_target     ?? 1.0;
    const dli         = d.dli_today      ?? null;
    const stage       = d.stage_label    ?? 'Germination';
    const stageDay    = d.stage_day      ?? '—';
    const stageDur    = d.stage_duration ?? '—';
    const phase       = d.phase          ?? 'night';
    const smoothGlide = d.smooth_glides  ?? false;
    const topology    = d.topology       ?? 'coordinated';
    const thermalRunaway = d.thermal_runaway ?? false;
    // Part 1.2: badge visibility now agrees with the popover's detail-lookup
    // — both keyed off there being an actual, specifically-identifiable
    // dropped entity, not the raw sensor_dropout boolean alone (which is
    // also true when no primary sensor is mapped at all — a configuration
    // gap, not a genuine hardware dropout — leaving the popover with
    // nothing real to show underneath a visible badge).
    const dropoutSensorEntities  = d.sensor_dropout_entities   || [];
    const dropoutActuatorEntities = d.actuator_dropout_entities || [];
    const sensorDropout   = dropoutSensorEntities.length > 0;
    const actuatorDropout = dropoutActuatorEntities.length > 0;

    const condEnabled  = d.enable_conditioning_room  ?? (topology === 'coordinated');
    const dryingEnabled = d.enable_drying_environment ?? false;
    const hasWeather   = !!d.outdoor_temp_c || !!d.outdoor_rh_pct;

    const phaseBadge = {
      day:     `<span class="badge bg-amber">☀ Day</span>`,
      night:   `<span class="badge bg-gray" title="It's currently a dark/night period per the lighting schedule — the Night VPD/temperature targets are active instead of Day.">☽ Night</span>`,
      sunrise: `<span class="badge bg-amber">↑ Sunrise Ramp</span>`,
      sunset:  `<span class="badge bg-amber">↓ Sunset Ramp</span>`,
    }[phase] ?? `<span class="badge bg-gray">—</span>`;

    const topoBadge = condEnabled
      ? `<span class="badge bg-purple" title="Coordinated: a Conditioning Room pre-treats air before it enters the Primary Grow Space, working together as one system.">⬡ Coordinated</span>`
      : `<span class="badge bg-blue" title="Standalone: the Primary Grow Space is controlled directly, with no separate Conditioning Room.">◈ Standalone</span>`;

    const stagePct = (stageDay !== '—' && stageDur !== '—')
      ? Math.min(100, Math.round((Number(stageDay) / Number(stageDur)) * 100))
      : 0;

    const alerts = [];
    if (thermalRunaway) alerts.push(`<span class="badge bg-red">🔥 Thermal Runaway</span>`);
    if (sensorDropout || actuatorDropout) {
      // Actuator dropout (can't heat/cool/exhaust) escalates to red — losing
      // control of hardware is more urgent than losing a passive reading.
      const badgeClass = actuatorDropout ? 'bg-red' : 'bg-amber';
      const badgeLabel = actuatorDropout ? '⚠ Actuator Dropout' : '⚠ Sensor Dropout';
      alerts.push(
        `<span class="badge ${badgeClass}" id="sensor-dropout-badge" style="cursor:pointer" title="Click for details">${badgeLabel}</span>`
      );
    }

    // Ambient bar (only if weather entity is mapped)
    const _moon = moonPhase(new Date());
    const ambientBar = hasWeather ? `
      <div class="card" style="margin-bottom:10px">
        <div class="card-title" style="display:flex;justify-content:space-between;align-items:center">
          <span>🌤 Ambient / Outdoor</span>
          <span title="${_moon.lore}" style="cursor:help;font-size:1rem" aria-label="${_moon.name}">
            ${_moon.icon} <span style="font-size:.7rem;color:var(--hx-text2)">${_moon.name}</span>
          </span>
        </div>
        <div class="g4">
          <div class="stat-cell">
            <div class="val">${fT(d.outdoor_temp_c)}</div><div class="lbl">Outdoor Temp</div>
          </div>
          <div class="stat-cell">
            <div class="val">${fRH(d.outdoor_rh_pct)}</div><div class="lbl">Outdoor RH</div>
          </div>
          <div class="stat-cell">
            <div class="val">${d.outdoor_condition ?? '—'}</div><div class="lbl">Condition</div>
          </div>
          <div class="stat-cell">
            <div class="val">${fT(d.outdoor_temp_forecast)}</div><div class="lbl">Forecast</div>
          </div>
        </div>
      </div>` : '';

    // Zone glance cards. `zone` is a JS property with no attribute
    // reflection (see HelixSparklineCard's `set zone(z)`), so it can't be
    // passed as a string-template attribute here — it's wired below via
    // `.zone = ...`, the same way `.hass =`/`.data =` are assigned elsewhere.
    const z2Card = `
      <helix-sparkline-card id="spark-tent"></helix-sparkline-card>`;

    const z1Card = condEnabled ? `
      <helix-sparkline-card id="spark-lung"></helix-sparkline-card>` : '';

    const dryCard = dryingEnabled ? `
      <helix-sparkline-card id="spark-dry"></helix-sparkline-card>` : '';

    // Appliance override chips
    const applianceChips = `
      <div class="card">
        <div class="card-title">⚡ Appliance Status</div>
        <div class="chip-row">
          ${overrideChip('Z2 Heater',    d.zone2_heater_entity,   d.zone2_heater_on,   h, true)}
          ${overrideChip('Z2 AC',        d.zone2_ac_entity,       d.zone2_ac_on,       h, true)}
          ${overrideChip('Z2 Humid',     d.zone2_humidifier_entity, d.zone2_humid_on,  h, true)}
          ${overrideChip('Z2 Dehumid',   d.zone2_dehumidifier_entity, d.zone2_dehumid_on, h, true)}
          ${overrideChip('Exhaust',      d.exhaust_entity,        d.exhaust_pct > 10,  h, true)}
          ${condEnabled ? overrideChip('Z1 Heater', d.zone1_heater_entity, d.zone1_heater_on, h, true) : ''}
          ${condEnabled ? overrideChip('Z1 AC', d.zone1_ac_entity, d.zone1_ac_on, h, true) : ''}
          ${condEnabled ? overrideChip('Z1 Dehumid', d.zone1_dehumidifier_entity, d.zone1_dehumid_on, h, true) : ''}
        </div>
      </div>`;

    this.shadowRoot.innerHTML = `
      <style>${BASE_CSS}:host{display:block;}</style>
      <!-- HUD Header -->
      <div class="card" style="background:linear-gradient(135deg,var(--hx-surface2) 0%,var(--hx-card) 100%)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:14px">
          <span style="font-size:1rem;font-weight:800">🌿 Helix Cultivate</span>
          ${topoBadge}${phaseBadge}
          ${smoothGlide ? '<span class="badge bg-accent" title="Smooth Glides: environmental targets (VPD/Temp/RH/Light) blend gradually day-by-day across a stage transition, instead of jumping instantly to the next stage\'s values.">✦ Smooth Glides</span>' : ''}
          ${alerts.join('')}
        </div>
        <div style="display:flex;align-items:center;justify-content:space-around;flex-wrap:wrap;gap:14px">
          <div style="display:flex;flex-direction:column;align-items:center;gap:4px">
            <helix-vpd-gauge id="hud-vpd-gauge"></helix-vpd-gauge>
            <span style="font-size:.68rem;color:var(--hx-text2)">LEAF VPD</span>
            <span style="font-size:.6rem;color:var(--hx-text2)" title="Green: within 0.08 kPa of target. Orange: within 0.20 kPa. Red: further off and needs attention.">
              🟢 On target · 🟠 Marginal · 🔴 Needs attention
            </span>
          </div>
          <div style="display:flex;flex-direction:column;align-items:center;gap:4px">
            <helix-dli-tracker id="hud-dli-tracker"></helix-dli-tracker>
            <span style="font-size:.68rem;color:var(--hx-text2)" title="Daily Light Integral: total useful (photosynthetically active) light received so far today, in mol/m², compared against the active stage's target.">DLI mol/m²</span>
          </div>
          <div style="text-align:center">
            <div style="font-size:1.1rem;font-weight:800">${stage}</div>
            <div style="font-size:.72rem;color:var(--hx-text2)">Day ${stageDay} / ${stageDur}</div>
            <div style="margin-top:6px;background:var(--hx-border);border-radius:6px;height:6px;overflow:hidden">
              <div style="width:${stagePct}%;height:6px;background:var(--hx-accent);border-radius:6px;transition:width .5s"></div>
            </div>
            <div style="font-size:.65rem;color:var(--hx-text2);margin-top:2px">${stagePct}% complete</div>
          </div>
          <div style="text-align:center">
            <div style="font-size:.68rem;color:var(--hx-text2)">Exhaust</div>
            <div style="font-size:1.3rem;font-weight:800;color:var(--hx-blue)">${fPct(d.exhaust_pct)}</div>
            <div style="font-size:.68rem;color:var(--hx-text2)">Cycle Cost</div>
            <div style="font-size:1.1rem;font-weight:800;color:var(--hx-green)">${d.cycle_cost ?? '—'}</div>
          </div>
        </div>
      </div>
      ${ambientBar}
      <!-- Zone Glance Cards -->
      <div class="sec">📡 Zone Telemetry &amp; Sparklines</div>
      <div class="g${condEnabled || dryingEnabled ? '2' : '1'}">
        ${z2Card}
        ${z1Card}
        ${dryCard}
      </div>
      ${applianceChips}
    `;

    // Wire up gauge sub-components
    const gauge = this.shadowRoot.querySelector('#hud-vpd-gauge');
    if (gauge) { gauge.vpd = vpd; gauge.target = vpdTarget; }
    const dliT = this.shadowRoot.querySelector('#hud-dli-tracker');
    if (dliT) { dliT.dli = dli; }

    // Sensor Dropout badge (Part 2.1) — click shows the specific flagged
    // sensor(s), sourced from the same tracking state already backing the
    // "primary_sensor_dropout" Repairs issue, plus a link to Settings >
    // Repairs for full detail/history. No new dropout-detection logic —
    // purely a UI connection to what already exists server-side.
    const dropoutBadge = this.shadowRoot.querySelector('#sensor-dropout-badge');
    if (dropoutBadge) {
      dropoutBadge.addEventListener('click', () => {
        this._showDropoutPopover = !this._showDropoutPopover;
        this._render();
      });
    }
    if (this._showDropoutPopover && (sensorDropout || actuatorDropout)) {
      const sensorEntities = d.sensor_dropout_entities || [];
      const actuatorEntities = d.actuator_dropout_entities || [];
      const popover = document.createElement('div');
      popover.style.cssText = `position:fixed;z-index:1000;background:var(--hx-surface2);
        border:1px solid var(--hx-border);border-radius:10px;padding:12px;max-width:280px;
        box-shadow:0 4px 16px rgba(0,0,0,.3);font-size:.78rem;color:var(--hx-text)`;
      const rect = dropoutBadge.getBoundingClientRect();
      popover.style.top = `${rect.bottom + 6}px`;
      popover.style.left = `${rect.left}px`;
      const sectionHtml = (title, entities) => entities.length
        ? `<div style="margin-bottom:4px;font-weight:600">${title}</div>
           <ul style="margin:0 0 8px;padding-left:18px">
             ${entities.map(e => `<li style="font-family:monospace;font-size:.72rem">${e}</li>`).join('')}
           </ul>`
        : '';
      popover.innerHTML = `
        <div style="font-weight:700;margin-bottom:6px">${actuatorDropout ? '⚠ Actuator Dropout' : '⚠ Sensor Dropout'}</div>
        ${sectionHtml('Actuators unreachable:', actuatorEntities)}
        ${sectionHtml('Sensors unavailable or stale:', sensorEntities)}
        <button id="dropout-popover-repairs" style="width:100%;padding:6px;border-radius:6px;border:1px solid var(--hx-border);
          background:none;color:var(--hx-text);cursor:pointer;font-size:.72rem">Open Settings → Repairs</button>
      `;
      this.shadowRoot.appendChild(popover);
      const repairsBtn = popover.querySelector('#dropout-popover-repairs');
      if (repairsBtn) {
        repairsBtn.addEventListener('click', () => {
          history.pushState(null, '', '/config/repairs');
          const evt = new CustomEvent('location-changed', { bubbles: true, composed: true });
          window.dispatchEvent(evt);
        });
      }
      // Dismiss on outside click (deferred so this same click doesn't
      // immediately close what it just opened).
      setTimeout(() => {
        const dismiss = (ev) => {
          if (!popover.contains(ev.target) && ev.target !== dropoutBadge) {
            this._showDropoutPopover = false;
            popover.remove();
            document.removeEventListener('click', dismiss);
          }
        };
        document.addEventListener('click', dismiss);
      }, 0);
    }

    // Wire up sparkline cards
    const tentSpark = this.shadowRoot.querySelector('#spark-tent');
    if (tentSpark) {
      tentSpark.hass = this._hass;
      tentSpark.zone = `🌱 ${d.zone2_name || 'Primary Grow Space'}`;
      tentSpark.data = {
        temp: d.upper_temp_c ?? d.mid_temp_c,
        rh: d.upper_rh_pct ?? d.mid_rh_pct,
        vpd: d.leaf_vpd,
        vpd_target: vpdTarget,
        vpd_target_min: d.vpd_target_min,
        vpd_target_max: d.vpd_target_max,
        temp_entity_id: `sensor.helix_cultivate_upper_canopy_temp`,
        rh_entity_id: `sensor.helix_cultivate_upper_canopy_rh`,
        vpd_entity_id: `sensor.helix_cultivate_leaf_vpd`,
      };
      tentSpark.timeframe = this._sparklineTimeframes['spark-tent'] || 'live';
    }
    if (condEnabled) {
      const lungSpark = this.shadowRoot.querySelector('#spark-lung');
      if (lungSpark) {
        lungSpark.hass = this._hass;
        lungSpark.zone = `🌬 ${d.zone1_name || 'Conditioning Room'}`;
        lungSpark.data = {
          temp: d.lung_temp_c,
          rh: d.lung_rh_pct,
          vpd: null,
          // VPD is leaf-referenced and the Conditioning Room has no canopy —
          // this is correct, existing behavior, not a bug. Flag it so the
          // card can show a clear "N/A" instead of a bare, ambiguous dash.
          vpd_no_canopy: true,
          vpd_target: vpdTarget,
          temp_entity_id: `sensor.helix_cultivate_lung_temp`,
          rh_entity_id: `sensor.helix_cultivate_lung_rh`,
          vpd_entity_id: null,
        };
        lungSpark.timeframe = this._sparklineTimeframes['spark-lung'] || 'live';
      }
    }
    if (dryingEnabled) {
      const drySpark = this.shadowRoot.querySelector('#spark-dry');
      if (drySpark) {
        drySpark.hass = this._hass;
        drySpark.zone = `🍃 ${d.drying_zone_name || 'Drying Room'}`;
        drySpark.data = {
          temp: d.drying_temp_c,
          rh: d.drying_rh_pct,
          vpd: null,
          vpd_target: 0,
          temp_entity_id: null,
          rh_entity_id: null,
          vpd_entity_id: null,
        };
        drySpark.timeframe = this._sparklineTimeframes['spark-dry'] || 'live';
      }
    }
  }

  // No Active Cycle (Part 1.3) — genuinely distinct empty state. The Start
  // New Cycle form itself lives on the Plant Cycle tab (the cleanest single
  // place for it); this button just requests that tab via a bubbling event
  // HelixPanel listens for, rather than duplicating the form here.
  _renderNoActiveCycle() {
    this.shadowRoot.innerHTML = `
      <style>${BASE_CSS}:host{display:block;}</style>
      <div class="card" style="text-align:center;padding:36px 20px">
        <div style="font-size:2.4rem;margin-bottom:8px">🌱</div>
        <div style="font-size:1.2rem;font-weight:800;margin-bottom:6px">No Active Cycle</div>
        <div style="font-size:.85rem;color:var(--hx-text2);max-width:420px;margin:0 auto 18px;line-height:1.5">
          Helix Cultivate isn't tracking a grow right now. Start a new cycle to begin
          day-counting, stage progression, and environmental control targets.
        </div>
        <button id="goto-start-cycle-btn" style="padding:11px 22px;border-radius:10px;border:none;
          background:var(--hx-accent);color:#fff;font-weight:700;cursor:pointer;font-size:.88rem">
          🌱 Start New Cycle
        </button>
      </div>`;

    const btn = this.shadowRoot.querySelector('#goto-start-cycle-btn');
    if (btn) {
      btn.addEventListener('click', () => {
        this.dispatchEvent(new CustomEvent('request-tab-change', {
          bubbles: true, composed: true, detail: { tab: 'plant_cycle' },
        }));
      });
    }
  }

  connectedCallback() { this._render(); }
}
customElements.define('helix-tab-telemetry', HelixTabTelemetry);

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Plant Cycle Engine  <helix-tab-cycle>
// ─────────────────────────────────────────────────────────────────────────────

// Mirrors const.py LIGHT_TYPE_OPTIONS/LIGHT_TYPE_LABELS. "supplemental" was
// removed as a Main Lighting fixture type — it's now the independent
// Supplemental Lighting system (its own entity + CONF_SUPPLEMENTAL_LIGHT_TYPE,
// which reuses this same options/labels pair for its own fixture-type field).
const LIGHT_TYPE_LABELS_JS = {
  led: 'LED',
  full_spectrum_led: 'Full Spectrum LED',
  hid_ballast: 'HID / Ballast',
  quantum_board: 'Quantum Board',
};
const LIGHT_TYPE_OPTIONS_JS = Object.keys(LIGHT_TYPE_LABELS_JS);

// Mirrors const.py TARIFF_OPTIONS/coordinator._current_tariff_rate()'s real
// mode semantics — "anytime" (flat rate), "dual" (Peak window + Off-Peak
// fallback), "triple" (Peak + Shoulder windows + Off-Peak fallback). Off-
// Peak has no window of its own — it's whatever time isn't Peak (or
// Shoulder, in Triple).
const TARIFF_MODE_LABELS_JS = {
  anytime: 'Anytime (flat rate)',
  dual: 'Dual (Peak / Off-Peak)',
  triple: 'Triple (Peak / Shoulder / Off-Peak)',
};
const TARIFF_MODE_OPTIONS_JS = Object.keys(TARIFF_MODE_LABELS_JS);

// Mirrors const.py PHOTOPERIOD_FLOWER_STAGES — used client-side only to
// derive the read-only "which schedule applies" preview; the coordinator is
// the actual authority on stage-group mapping.
const PHOTOPERIOD_FLOWER_STAGES_JS = new Set(['stretch', 'peak_flower', 'ripening']);

// v1.5.0 Part 2.2: the single formula for "what lighting-hours value does
// Growth Mode actually compute for this stage" — mirrors
// HelixCoordinator.computed_photoperiod_hours()/_light_schedule_params_for_stage()
// exactly (same branches, same stage-group mapping). Every stage's Profile
// Card reads its own value through this, never an independent per-stage
// number, so it can never diverge from what's actually being scheduled.
function _computedPhotoperiodHours(d, stage) {
  if (stage === 'drying') return 0.0;
  const mode = d.growth_mode === 'autoflower' ? 'autoflower' : 'photoperiod';
  if (mode === 'autoflower') return d.af_light_hours ?? 18.0;
  return PHOTOPERIOD_FLOWER_STAGES_JS.has(stage) ? (d.pp_flower_hours ?? 12.0) : (d.pp_veg_hours ?? 18.0);
}

// Mirrors const.py STAGE_DEFAULT_DURATIONS — the day-count fallback when no
// user-persisted stage_targets_{stage}.duration_days override exists yet.
const STAGE_DEFAULT_DURATIONS_JS = {
  germination: 4, seedling: 10, early_veg: 14, late_veg: 14,
  stretch: 14, peak_flower: 28, ripening: 14, drying: 10,
};

// v1.5.0 Part 3.2: mode-aware recommended-range guidance — genuinely
// reasonable horticultural ranges per stage, scoped only to Autoflower vs.
// Photoperiod (never strain-specific). Drying is the same regardless of
// growth mode — it's a post-harvest cure, not a live-plant response.
const DAY_COUNT_GUIDANCE_JS = {
  autoflower: {
    germination: '2–5 days', seedling: '5–10 days', early_veg: '7–14 days',
    late_veg: '7–14 days', stretch: '5–10 days', peak_flower: '21–35 days',
    ripening: '5–10 days', drying: '7–14 days',
  },
  photoperiod: {
    germination: '3–7 days', seedling: '7–14 days', early_veg: '7–21 days',
    late_veg: '7–21 days', stretch: '7–21 days', peak_flower: '21–35 days',
    ripening: '7–14 days', drying: '7–14 days',
  },
};
function _dayCountGuidance(d, stage) {
  const mode = d.growth_mode === 'autoflower' ? 'autoflower' : 'photoperiod';
  return DAY_COUNT_GUIDANCE_JS[mode][stage] || 'Typically 7–14 days';
}

const RAMP_PRESET_LABELS_JS = {
  gentle: 'Gentle (~30 min)',
  standard: 'Standard (~15 min)',
  fast: 'Fast (~5 min)',
  custom: 'Custom',
};

const STAGE_META = {
  germination: { label:'Germination',      icon:'🌰' },
  seedling:    { label:'Seedling',         icon:'🌱' },
  early_veg:   { label:'Early Veg',        icon:'🍃' },
  late_veg:    { label:'Late Veg',         icon:'🌿' },
  stretch:     { label:'Stretch/Pre-Flower', icon:'↑' },
  peak_flower: { label:'Peak Flower',      icon:'🌸' },
  ripening:    { label:'Ripening/Flush',   icon:'🟡' },
  drying:      { label:'Drying',           icon:'🍃' },
};

// Mirrors const.py STAGE_DAYNIGHT_DEFAULTS — used as the frontend fallback
// baseline when no user-persisted stage_targets_{stage} override exists yet.
const STAGE_DAYNIGHT_DEFAULTS_JS = {
  germination: { day_temp_c:24.0, night_temp_c:22.0, day_vpd_min:0.35, day_vpd_max:0.50, night_vpd_min:0.30, night_vpd_max:0.45, light_intensity_pct:50, fan_speed_pct:25 },
  seedling:    { day_temp_c:23.5, night_temp_c:21.0, day_vpd_min:0.50, day_vpd_max:0.70, night_vpd_min:0.40, night_vpd_max:0.60, light_intensity_pct:60, fan_speed_pct:30 },
  early_veg:   { day_temp_c:24.0, night_temp_c:20.0, day_vpd_min:0.60, day_vpd_max:0.90, night_vpd_min:0.45, night_vpd_max:0.65, light_intensity_pct:70, fan_speed_pct:35 },
  late_veg:    { day_temp_c:24.0, night_temp_c:20.0, day_vpd_min:0.80, day_vpd_max:1.05, night_vpd_min:0.60, night_vpd_max:0.80, light_intensity_pct:80, fan_speed_pct:40 },
  stretch:     { day_temp_c:25.0, night_temp_c:21.0, day_vpd_min:0.90, day_vpd_max:1.15, night_vpd_min:0.70, night_vpd_max:0.90, light_intensity_pct:90, fan_speed_pct:45 },
  peak_flower: { day_temp_c:26.0, night_temp_c:22.0, day_vpd_min:1.10, day_vpd_max:1.40, night_vpd_min:0.85, night_vpd_max:1.10, light_intensity_pct:100, fan_speed_pct:50 },
  ripening:    { day_temp_c:24.0, night_temp_c:18.0, day_vpd_min:1.30, day_vpd_max:1.55, night_vpd_min:1.00, night_vpd_max:1.25, light_intensity_pct:85, fan_speed_pct:45 },
  drying:      { day_temp_c:15.5, night_temp_c:15.5, day_vpd_min:1.05, day_vpd_max:1.15, night_vpd_min:1.05, night_vpd_max:1.15, light_intensity_pct:0, fan_speed_pct:40 },
};

function _svpKpa(tC) { return 0.6108 * Math.exp(17.27 * tC / (tC + 237.3)); }
function _rhGuideForVpd(tempC, targetVpd, leafOffsetC = -2.5) {
  const tLeaf = tempC + leafOffsetC;
  const svpLeaf = _svpKpa(tLeaf), svpAir = _svpKpa(tempC);
  if (!svpAir) return null;
  const rhFrac = (svpLeaf - targetVpd) / svpAir;
  return Math.max(0, Math.min(100, rhFrac * 100));
}

function _vpdBandSVG(minVal, maxVal, lo = 0.3, hi = 1.8, width = 220, height = 14) {
  const x1 = ((minVal - lo) / (hi - lo)) * width;
  const x2 = ((maxVal - lo) / (hi - lo)) * width;
  const bx = Math.max(0, Math.min(width, x1));
  const bw = Math.max(2, Math.min(width, x2) - bx);
  return `<svg width="${width}" height="${height}" style="display:block;margin-top:2px">
    <rect x="0" y="4" width="${width}" height="6" rx="3" fill="var(--hx-border,#333)"/>
    <rect x="${bx}" y="4" width="${bw}" height="6" rx="3" fill="var(--hx-blue,#209cee)" opacity="0.75"/>
  </svg>`;
}

class HelixTabCycle extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._editingStage = null;    // null = show active stage; slug = edit that stage
    this._editingPeriod = 'day';  // 'day' | 'night'
    this._showHarvestForm = false;
    this._harvestReport = null;   // set after successful close_out_harvest WS call
    this._harvestError = null;
    this._showExportModal = false;
    this._showImportModal = false;
    this._exportYaml = '';
    this._importError = null;
    // Start New Cycle form draft state (Part 1.2)
    this._startGrowthMode = 'photoperiod';
    this._startDate = new Date().toISOString().slice(0, 10);
    this._startStage = 'germination';
    this._startError = null;
    this._startSaving = false;
    // Abort Cycle confirmation (Part 1.5) — a second, explicit step so a
    // grower never accidentally aborts when they meant to close out a
    // real harvest, or vice versa.
    this._showAbortConfirm = false;
    this._abortSaving = false;
    // Space Now Empty / Harvest Complete for a dedicated Drying Room
    // (v1.4.0 Parts 4.2/9) — genuinely independent of the no-dedicated-room
    // harvest form above.
    this._showSpaceEmptyConfirm = false;
    this._spaceEmptySaving = false;
    this._showDryingHarvestForm = false;
    this._dryingHarvestUnit = 'g'; // 'g' | 'oz'
    this._dryingHarvestError = null;
    this._dryingHarvestReport = null;
  }

  set hass(h) { this._hass = h; }
  set data(d) { this._data = d; this._render(); }

  _callService(domain, service, data) {
    if (this._hass) this._hass.callService(domain, service, data);
  }

  // ── Harvest close-out (Phase 11D) ─────────────────────────────────────────

  async _submitHarvest(wetWeightG, dryWeightG) {
    const entryId = (this._data || {}).entry_id;
    if (!this._hass) return;
    this._harvestError = null;
    try {
      const result = await this._hass.callWS({
        type: 'helix_cultivate/close_out_harvest',
        wet_weight_g: wetWeightG,
        dry_weight_g: dryWeightG,
      });
      this._harvestReport = result;
      this._showHarvestForm = false;
      this._render();

      // Phase 12D — "Perfect Thermal Control" achievement: awarded only when
      // no thermal runaway fired at any point during the just-completed cycle.
      const panel = this.closest('helix-panel');
      if (panel && panel._eggs) {
        if (!panel._eggs._thermalRunawayThisCycle) {
          panel._eggs._showAchievement(
            panel,
            '🏆 Perfect Thermal Control',
            'Zero thermal runaways this cycle!'
          );
        }
        // Reset the flag for the fresh cycle that just started.
        panel._eggs._thermalRunawayThisCycle = false;
      }
    } catch (e) {
      this._harvestError = (e && e.message) || 'Failed to archive harvest';
      this._render();
    }
  }

  _closeHarvestReport() {
    this._harvestReport = null;
    this._editingStage = null;
    this._render();
    // Trigger a full panel refresh so the tab reflects the reset cycle
    const panel = this.closest('helix-panel');
    if (panel && typeof panel._update === 'function') panel._update();
  }

  // ── Recipe export / import (Phase 11E) ────────────────────────────────────

  async _openExportModal() {
    if (!this._hass) return;
    try {
      const result = await this._hass.callWS({ type: 'helix_cultivate/export_recipe' });
      this._exportYaml = result.yaml_text || '';
    } catch (e) {
      this._exportYaml = `# Export failed: ${(e && e.message) || e}`;
    }
    this._showExportModal = true;
    this._render();
  }

  async _submitImport(yamlText) {
    const entryId = (this._data || {}).entry_id;
    if (!this._hass || !entryId) return;
    this._importError = null;
    try {
      await this._hass.callWS({
        type: 'helix_cultivate/import_recipe',
        entry_id: entryId,
        yaml_text: yamlText,
      });
      this._showImportModal = false;
      this._render();
      const panel = this.closest('helix-panel');
      if (panel && typeof panel._update === 'function') panel._update();
    } catch (e) {
      this._importError = (e && e.message) || 'Import failed';
      this._render();
    }
  }

  // Part 1.1 (v1.5.0): immediate write to the single shared growth_mode
  // config value — the same key Primary Grow Space's own toggle (batched
  // into its "Save Lighting Schedule" flow) ultimately writes to, so
  // there is never a possibility of the two disagreeing. Optimistically
  // patches local data so this instance re-renders immediately rather
  // than waiting for the next coordinator poll.
  async _setGrowthMode(mode) {
    const entryId = (this._data || {}).entry_id;
    if (!this._hass || !entryId) return;
    try {
      await this._hass.callWS({
        type: 'helix_cultivate/update_settings_fields',
        entry_id: entryId,
        fields: { growth_mode: mode },
      });
      this._data = { ...(this._data || {}), growth_mode: mode };
      this._render();
    } catch (e) {
      console.error('Helix Cultivate: growth mode update failed', e);
    }
  }

  _stageValue(stage, key) {
    const persisted = (this._data || {})[`stage_targets_${stage}`];
    if (persisted && persisted[key] !== undefined) return persisted[key];
    return (STAGE_DAYNIGHT_DEFAULTS_JS[stage] || STAGE_DAYNIGHT_DEFAULTS_JS.germination)[key];
  }

  // v1.5.0 Part 3.1: duration_days lives in its own default table
  // (STAGE_DEFAULT_DURATIONS_JS, mirroring const.py's STAGE_DEFAULT_
  // DURATIONS) rather than STAGE_DAYNIGHT_DEFAULTS_JS, matching the same
  // separation the backend's StageManager._duration() keeps from _profile().
  _stageDuration(stage) {
    const persisted = (this._data || {})[`stage_targets_${stage}`];
    if (persisted && persisted.duration_days !== undefined) return persisted.duration_days;
    return STAGE_DEFAULT_DURATIONS_JS[stage] ?? 14;
  }

  // Reads the currently-displayed slider values straight from the DOM and
  // saves them in a single explicit action — no draft object that would need
  // to survive this element being destroyed/recreated on a tab switch.
  async _saveStageTargetsFromDom(stage, isDay) {
    const q = (id) => this.shadowRoot.querySelector(id);
    const tempKey = isDay ? 'day_temp_c' : 'night_temp_c';
    const vpdMinKey = isDay ? 'day_vpd_min' : 'night_vpd_min';
    const vpdMaxKey = isDay ? 'day_vpd_max' : 'night_vpd_max';
    const targets = {
      [tempKey]: parseFloat(q('#temp-anchor-slider').value),
      [vpdMinKey]: parseFloat(q('#vpd-min-slider').value),
      [vpdMaxKey]: parseFloat(q('#vpd-max-slider').value),
      light_intensity_pct: parseFloat(q('#light-slider').value),
      fan_speed_pct: parseFloat(q('#fan-slider').value),
    };
    const durationEl = q('#stage-duration-slider');
    if (durationEl) targets.duration_days = parseInt(durationEl.value, 10);

    const entryId = (this._data || {}).entry_id;
    const statusEl = this.shadowRoot.querySelector('#stage-save-status');
    if (!this._hass || !entryId) {
      if (statusEl) statusEl.textContent = '❌ Save failed — no config entry found';
      return;
    }
    // Deliberately do NOT call this._render() after this WS round trip: the
    // panel's own coordinator poll (up to ~30s away) is what refreshes
    // this._data with the just-saved values, and re-rendering from the
    // sliders' backing data before that arrives would visually snap the
    // sliders back to their pre-save values. Update the status text in
    // place instead, leaving the sliders exactly where the user left them.
    if (statusEl) statusEl.textContent = 'Saving…';
    try {
      await this._hass.callWS({
        type: 'helix_cultivate/update_stage_targets',
        entry_id: entryId,
        stage,
        targets,
      });
      if (statusEl) statusEl.textContent = '✅ Saved';
    } catch (e) {
      console.error('Helix Cultivate: stage target save failed', e);
      if (statusEl) statusEl.textContent = '❌ Save failed — see console';
    }
  }

  _render() {
    const d = this._data || {};

    // No Active Cycle (Part 1.3) — the Plant Cycle tab is the primary home
    // for the Start New Cycle form; replaces the entire stage timeline/
    // profile-editor view rather than showing a stage that was never
    // actually begun.
    if (d.cycle_state === 'not_started') {
      this._renderNoActiveCycle();
      return;
    }

    const activeStage = d.grow_stage_slug || 'germination';
    const dedicatedDryingRoom = d.enable_drying_environment === true;
    // Never two editable surfaces for the same data: once a dedicated
    // Drying Room exists, all Drying editing happens exclusively in
    // helix-tab-drying. If the flag flips on post-setup while this tab
    // still had Drying open for editing, fall back to the active stage
    // immediately rather than silently re-showing a stale edit surface.
    if (dedicatedDryingRoom && this._editingStage === 'drying') {
      this._editingStage = null;
    }
    const stage = this._editingStage || activeStage;
    const stageMeta = STAGE_META[stage] || STAGE_META.germination;
    const isActiveStage = stage === activeStage;
    const stageDay = d.stage_day ?? '—';
    const stageDur = d.stage_duration ?? '—';
    const smoothGlides = d.smooth_glides ?? false;
    const progression = d.progression_mode || 'manual';
    const period = this._editingPeriod;
    const isDay = period === 'day';
    const cycleComplete = d.cycle_complete === true;
    // Single control surface (2.B1): once a dedicated Drying Room exists,
    // this tab must never show an editable Drying profile — even when the
    // grow has naturally progressed to the Drying stage and `stage` resolves
    // here via `activeStage` rather than explicit navigation. The timeline
    // filter above only blocks clicking into it; this catches the natural
    // case too.
    const dryingHiddenNotice = stage === 'drying' && dedicatedDryingRoom;
    // Without a dedicated Drying Room, Drying is just another stage here —
    // but per 2.A5/2.B1 it also needs the 60/60 lock/unlock toggle and the
    // constant/cyclic airflow controls that would otherwise only live in
    // helix-tab-drying, since there's nowhere else for the grower to set them.
    const showDryingAirflowControls = stage === 'drying' && !dedicatedDryingRoom;
    const isDryingUnlocked = !!d.is_drying_unlocked;
    const dryingAirflowMode = d.drying_airflow_mode || 'constant';

    // ── Harvest close-out section (Phase 11D) ────────────────────────────────
    let harvestSectionHtml = '';
    if (this._harvestReport) {
      const r = this._harvestReport;
      const ratio = (r.wet_weight_g > 0) ? (r.dry_weight_g / r.wet_weight_g) * 100 : 0;
      const plannedDurations = d.stage_durations_planned || {};
      const stageDurRows = Object.entries(r.stage_durations || {}).map(([k, v]) => {
        const meta = STAGE_META[k] || { icon: '🌱', label: k };
        const planned = plannedDurations[k];
        return `<div class="metric-row">
          <span class="metric-label">${meta.icon} ${meta.label}</span>
          <span class="metric-val">${v} d${planned != null ? ` (planned ${planned})` : ''}</span>
        </div>`;
      }).join('');
      harvestSectionHtml = `
        <div class="card" style="border:1px solid var(--hx-green,#3ecf6a)">
          <div class="card-title">🌾 Harvest Report — ${r.record_id}</div>
          <div style="font-size:.72rem;color:var(--hx-text2);margin-bottom:8px">Archived: ${r.archived_at}</div>
          <div class="g3">
            <div class="stat-cell"><div class="val">${fn(r.wet_weight_g,1)} g</div><div class="lbl">Wet</div></div>
            <div class="stat-cell"><div class="val">${fn(r.dry_weight_g,1)} g</div><div class="lbl">Dry</div></div>
            <div class="stat-cell"><div class="val">${fn(ratio,1)}%</div><div class="lbl">Ratio</div></div>
          </div>
          <div class="metric-row"><span class="metric-label">VPD In-Range</span><span class="metric-val">${fn(r.vpd_in_range_pct,1)}%</span></div>
          <div class="metric-row"><span class="metric-label">Energy</span><span class="metric-val">${fn(r.cycle_kwh,2)} kWh</span></div>
          <div class="metric-row"><span class="metric-label">Cost</span><span class="metric-val">$${fn(r.cycle_cost_usd,2)}</span></div>
          <div class="metric-row"><span class="metric-label">Yield Efficiency</span><span class="metric-val">$${fn(r.dollar_per_g,3)}/g</span></div>
          <div class="metric-row"><span class="metric-label">Revenue</span><span class="metric-val">$${fn(r.revenue_usd,2)}</span></div>
          <div class="sec">Stage Durations</div>
          ${stageDurRows}
          ${r.timelapse_gif_url ? `
            <div class="sec">🎞 Grow Time-Lapse</div>
            <img src="${r.timelapse_gif_url}" alt="Grow cycle time-lapse"
              style="width:100%;border-radius:8px;border:1px solid var(--hx-border)"/>
          ` : ''}
          <button id="close-harvest-report-btn" style="margin-top:12px;width:100%;padding:10px;border-radius:8px;
            border:none;background:var(--hx-accent);color:#fff;font-weight:700;cursor:pointer">Start New Cycle</button>
        </div>`;
    } else if (cycleComplete) {
      if (this._showHarvestForm) {
        harvestSectionHtml = `
          <div class="card" style="border:1px solid var(--hx-amber,#f0a020)">
            <div class="card-title">🌾 Close Out Harvest</div>
            ${this._harvestError ? `<div class="badge bg-red" style="margin-bottom:8px">${this._harvestError}</div>` : ''}
            <div class="slider-row">
              <span class="slider-lbl">Wet Weight (g)</span>
              <input type="number" id="wet-weight-input" min="0" step="0.1" style="flex:1;padding:6px;border-radius:6px;
                border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
            </div>
            <div class="slider-row">
              <span class="slider-lbl">Dry Weight (g)</span>
              <input type="number" id="dry-weight-input" min="0" step="0.1" style="flex:1;padding:6px;border-radius:6px;
                border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
            </div>
            <div style="display:flex;gap:8px;margin-top:10px">
              <button id="archive-harvest-btn" style="flex:1;padding:10px;border-radius:8px;border:none;
                background:var(--hx-green,#3ecf6a);color:#fff;font-weight:700;cursor:pointer">Archive &amp; Reset Cycle</button>
              <button id="cancel-harvest-btn" style="flex:1;padding:10px;border-radius:8px;border:1px solid var(--hx-border);
                background:none;color:var(--hx-text);cursor:pointer">Cancel</button>
            </div>
          </div>`;
      } else {
        harvestSectionHtml = `
          <div class="card" style="border:1px solid var(--hx-amber,#f0a020)">
            <div class="card-title">🌾 Grow Cycle Complete</div>
            <div style="font-size:.78rem;color:var(--hx-text2);margin-bottom:10px">
              The drying stage has finished. Close out this harvest to archive the cycle and start fresh.
            </div>
            <button id="open-harvest-form-btn" style="width:100%;padding:10px;border-radius:8px;border:none;
              background:var(--hx-amber,#f0a020);color:#111;font-weight:700;cursor:pointer">🌾 Close Out Harvest</button>
          </div>`;
      }
    }

    // ── Space Now Empty / Harvest Complete for a dedicated Drying Room
    // (v1.4.0 Parts 4.2/9) — genuinely independent of the harvest section
    // above: this room's occupancy and this action exist only when a
    // dedicated Drying Room is configured, and Harvest Complete here
    // targets that specific transferred batch's cycle_id, not whatever
    // Primary Grow Space is doing right now.
    let dryingHandoffHtml = '';
    if (dedicatedDryingRoom && d.zone2_occupied && !d.drying_occupied) {
      dryingHandoffHtml = this._showSpaceEmptyConfirm ? `
        <div class="card" style="border:1px solid var(--hx-amber,#f0a020)">
          <div class="card-title">📦 Harvest — Space Now Empty</div>
          <div style="font-size:.78rem;color:var(--hx-text2);margin-bottom:10px">
            Confirms the current batch has physically moved to the Drying Room. This transfers
            occupancy only — it does not touch this batch's stage tracking or accumulated data.
          </div>
          <div style="display:flex;gap:8px">
            <button id="confirm-space-empty-btn" ${this._spaceEmptySaving ? 'disabled' : ''} style="flex:1;padding:10px;
              border-radius:8px;border:none;background:var(--hx-amber,#f0a020);color:#111;font-weight:700;cursor:pointer">
              ${this._spaceEmptySaving ? 'Saving…' : 'Yes, Space Is Now Empty'}
            </button>
            <button id="cancel-space-empty-btn" style="flex:1;padding:10px;border-radius:8px;border:1px solid var(--hx-border);
              background:none;color:var(--hx-text);cursor:pointer">Cancel</button>
          </div>
        </div>` : `
        <div class="card">
          <div class="card-title">📦 Harvest — Space Now Empty</div>
          <div style="font-size:.78rem;color:var(--hx-text2);margin-bottom:10px">
            Once this batch has physically moved to the Drying Room, mark Primary Grow Space
            empty so it's free for Deep Calibration or a new cycle — independent of this
            batch's own Harvest Complete, which stays available for it separately later.
          </div>
          <button id="open-space-empty-btn" style="width:100%;padding:10px;border-radius:8px;
            border:1px solid var(--hx-amber,#f0a020);background:none;color:var(--hx-amber,#f0a020);
            font-weight:700;cursor:pointer">📦 Space Now Empty…</button>
        </div>`;
    }

    let dryingHarvestCompleteHtml = '';
    if (dedicatedDryingRoom && d.drying_occupied) {
      if (this._dryingHarvestReport) {
        const r = this._dryingHarvestReport;
        dryingHarvestCompleteHtml = `
          <div class="card" style="border:1px solid var(--hx-green,#3ecf6a)">
            <div class="card-title">🌾 Drying Room Harvest Complete — ${r.record_id}</div>
            <div class="metric-row"><span class="metric-label">Dry Weight</span>
              <span class="metric-val">${fn(r.dry_weight_g,1)} g</span></div>
            <div class="metric-row"><span class="metric-label">$/gram</span>
              <span class="metric-val">$${fn(r.dollar_per_g,4)}</span></div>
            <button id="close-drying-harvest-report-btn" style="margin-top:10px;width:100%;padding:9px;
              border-radius:8px;border:none;background:var(--hx-accent);color:#fff;font-weight:700;
              cursor:pointer">Close</button>
          </div>`;
      } else if (this._showDryingHarvestForm) {
        dryingHarvestCompleteHtml = `
          <div class="card" style="border:1px solid var(--hx-green,#3ecf6a)">
            <div class="card-title">🌾 Harvest Complete — Drying Room</div>
            ${this._dryingHarvestError ? `<div class="badge bg-red" style="margin-bottom:8px">${this._dryingHarvestError}</div>` : ''}
            <div style="display:flex;gap:6px;margin-bottom:8px">
              <button class="drying-harvest-unit-btn ${this._dryingHarvestUnit === 'g' ? 'active' : ''}" data-unit="g"
                style="flex:1;padding:6px;border-radius:6px;border:1px solid var(--hx-border);cursor:pointer;
                background:${this._dryingHarvestUnit === 'g' ? 'var(--hx-accent)' : 'none'};
                color:${this._dryingHarvestUnit === 'g' ? '#fff' : 'var(--hx-text)'}">Grams</button>
              <button class="drying-harvest-unit-btn ${this._dryingHarvestUnit === 'oz' ? 'active' : ''}" data-unit="oz"
                style="flex:1;padding:6px;border-radius:6px;border:1px solid var(--hx-border);cursor:pointer;
                background:${this._dryingHarvestUnit === 'oz' ? 'var(--hx-accent)' : 'none'};
                color:${this._dryingHarvestUnit === 'oz' ? '#fff' : 'var(--hx-text)'}">Ounces</button>
            </div>
            <div class="slider-row">
              <span class="slider-lbl">Wet Weight (${this._dryingHarvestUnit})</span>
              <input type="number" id="drying-wet-weight-input" min="0" step="0.1" style="flex:1;padding:6px;
                border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
            </div>
            <div class="slider-row">
              <span class="slider-lbl">Dry Weight (${this._dryingHarvestUnit})</span>
              <input type="number" id="drying-dry-weight-input" min="0" step="0.1" style="flex:1;padding:6px;
                border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
            </div>
            <div style="display:flex;gap:8px;margin-top:10px">
              <button id="archive-drying-harvest-btn" style="flex:1;padding:10px;border-radius:8px;border:none;
                background:var(--hx-green,#3ecf6a);color:#fff;font-weight:700;cursor:pointer">Archive This Batch</button>
              <button id="cancel-drying-harvest-btn" style="flex:1;padding:10px;border-radius:8px;
                border:1px solid var(--hx-border);background:none;color:var(--hx-text);cursor:pointer">Cancel</button>
            </div>
          </div>`;
      } else {
        dryingHarvestCompleteHtml = `
          <div class="card" style="border:1px solid var(--hx-green,#3ecf6a)">
            <div class="card-title">🌾 Harvest Complete — Drying Room</div>
            ${d.drying_batch_elapsed_days != null ? `<div style="font-size:.85rem;font-weight:700;margin-bottom:6px">
              Day ${d.drying_batch_elapsed_days} of drying
            </div>` : ''}
            <div style="font-size:.78rem;color:var(--hx-text2);margin-bottom:10px">
              Closes out the batch currently curing in the Drying Room — independent of
              whatever Primary Grow Space is doing now, even a fresh new cycle.
            </div>
            <button id="open-drying-harvest-form-btn" style="width:100%;padding:10px;border-radius:8px;
              border:none;background:var(--hx-green,#3ecf6a);color:#fff;font-weight:700;
              cursor:pointer">🌾 Harvest Complete…</button>
          </div>`;
      }
    }

    // Stage timeline
    // Drying is fully absent from the clickable timeline (not disabled) once
    // a dedicated Drying Room exists — matching how disabled canopy tiers
    // are handled elsewhere. Still shown when no dedicated room is
    // configured, since there'd be nowhere else to edit it.
    const stages = Object.entries(STAGE_META).filter(
      ([key]) => key !== 'drying' || !dedicatedDryingRoom
    );
    const currentIdx = stages.findIndex(([k]) => k === activeStage);

    const timelineItems = stages.map(([key, meta], idx) => {
      const isPast = idx < currentIdx;
      const isCurrent = idx === currentIdx;
      const isEditing = key === stage;
      let style = isCurrent
        ? 'background:var(--hx-accent);color:#fff;font-weight:700;'
        : isPast
          ? 'background:var(--hx-green);color:#fff;opacity:.7;'
          : 'background:var(--hx-surface2);color:var(--hx-text2);';
      if (isEditing && !isCurrent) style += 'outline:2px solid var(--hx-blue,#209cee);';
      return `<div style="padding:5px 8px;border-radius:8px;font-size:.72rem;text-align:center;${style}
        cursor:pointer" data-stage="${key}">
        ${meta.icon} ${meta.label}${isCurrent ? ' ★' : ''}
      </div>`;
    }).join('');

    // Resolved stage-period values (draft > persisted > STAGE_DAYNIGHT_DEFAULTS_JS)
    const tempKey = isDay ? 'day_temp_c' : 'night_temp_c';
    const vpdMinKey = isDay ? 'day_vpd_min' : 'night_vpd_min';
    const vpdMaxKey = isDay ? 'day_vpd_max' : 'night_vpd_max';
    const tempAnchor = this._stageValue(stage, tempKey);
    const vpdMin = this._stageValue(stage, vpdMinKey);
    const vpdMax = this._stageValue(stage, vpdMaxKey);
    const lightPct = this._stageValue(stage, 'light_intensity_pct');
    const fanPct = this._stageValue(stage, 'fan_speed_pct');
    // v1.5.0 Part 2.2: no longer an independent per-stage value — always a
    // live, read-only reflection of what Growth Mode actually computes.
    const photoperiod = _computedPhotoperiodHours(d, stage);
    // v1.5.0 Part 3: genuinely editable, wired to real auto-advance timing
    // (StageManager._duration()) — not a disconnected display number.
    const stageDuration = this._stageDuration(stage);
    const durationGuidance = _dayCountGuidance(d, stage);

    const rhLo = _rhGuideForVpd(tempAnchor, vpdMax);
    const rhHi = _rhGuideForVpd(tempAnchor, vpdMin);
    const rhGuideText = (rhLo != null && rhHi != null)
      ? `Guide: ~${fn(rhLo,0)}–${fn(rhHi,0)}% RH at ${fn(tempAnchor,1)}°C`
      : '—';

    // Part 1.2 (v1.5.0): reuses CONF_ZONE2_OCCUPIED — the same flag the
    // Environmental Learning gating work established — rather than new
    // tracking. Applies identically to Primary Grow Space's own copy of
    // this toggle (helix-tab-growspace).
    const zone2OccupiedCycle = d.zone2_occupied === true;
    const growthModeCycle = d.growth_mode === 'autoflower' ? 'autoflower' : 'photoperiod';
    const growthModeCardHtml = `
      <div class="card">
        <div class="card-title">🌗 Growth Mode</div>
        <div class="hx-period-toggle" style="display:flex;gap:6px">
          <button class="cycle-growth-mode-btn ${growthModeCycle === 'autoflower' ? 'active' : ''}" data-mode="autoflower"
            ${zone2OccupiedCycle ? 'disabled' : ''}
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);
            cursor:${zone2OccupiedCycle ? 'not-allowed' : 'pointer'};opacity:${zone2OccupiedCycle ? '0.6' : '1'};
            background:${growthModeCycle === 'autoflower' ? 'var(--hx-blue,#209cee)' : 'none'};
            color:${growthModeCycle === 'autoflower' ? '#fff' : 'var(--hx-text)'};font-weight:600">🌻 Autoflower</button>
          <button class="cycle-growth-mode-btn ${growthModeCycle === 'photoperiod' ? 'active' : ''}" data-mode="photoperiod"
            ${zone2OccupiedCycle ? 'disabled' : ''}
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);
            cursor:${zone2OccupiedCycle ? 'not-allowed' : 'pointer'};opacity:${zone2OccupiedCycle ? '0.6' : '1'};
            background:${growthModeCycle === 'photoperiod' ? 'var(--hx-blue,#209cee)' : 'none'};
            color:${growthModeCycle === 'photoperiod' ? '#fff' : 'var(--hx-text)'};font-weight:600">📅 Photoperiod</button>
        </div>
        ${zone2OccupiedCycle ? `
        <div style="font-size:.7rem;color:var(--hx-text2);margin-top:6px">
          🔒 Locked while a cycle occupies Primary Grow Space — changing Growth
          Mode mid-cycle would abruptly change the active lighting schedule.
          Editable again once this space is empty.
        </div>` : ''}
      </div>`;

    this.shadowRoot.innerHTML = `
      <style>${BASE_CSS}:host{display:block;}</style>
      <!-- Part 6 (v1.5.0): explanatory copy, verbatim -->
      <div style="font-size:.78rem;color:var(--hx-text2);margin-bottom:10px;line-height:1.5">
        This is where you set up each growth stage's targets — temperature, VPD, lighting, and
        how many days it should typically run. Use the recommended defaults as-is, or adjust
        them to match your own strain and setup. Changes here are permanent and apply
        immediately, even to the stage you're currently in.
      </div>
      <!-- Stage timeline -->
      <div class="card">
        <div class="card-title">🌱 Grow Stage Timeline</div>
        <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:12px">${timelineItems}</div>
        <div class="g2">
          <div class="stat-cell">
            <div class="val" style="font-size:1.3rem">${STAGE_META[activeStage].icon}</div>
            <div class="val">${STAGE_META[activeStage].label}</div>
            <div class="lbl">Active Stage</div>
          </div>
          <div class="stat-cell">
            <div class="val">Day ${stageDay} / ${stageDur}</div>
            <div class="lbl">Progress</div>
            <div style="margin-top:6px;background:var(--hx-border);border-radius:4px;height:5px">
              <div style="width:${(stageDay !== '—' && stageDur !== '—') ? Math.min(100,Math.round(stageDay/stageDur*100)) : 0}%;
                height:5px;background:var(--hx-accent);border-radius:4px;transition:width .5s"></div>
            </div>
          </div>
        </div>
      </div>
      ${harvestSectionHtml}
      ${dryingHandoffHtml}
      ${dryingHarvestCompleteHtml}
      <!-- Part 1.1 (v1.5.0): Growth Mode surfaced directly above the
           Profile Card — the exact same config value as Primary Grow
           Space's own toggle, never a separate per-stage setting. -->
      ${growthModeCardHtml}
      <!-- Day/Night stage profile editor -->
      ${dryingHiddenNotice ? `
      <div class="card">
        <div class="card-title">📊 ${stageMeta.icon} ${stageMeta.label} Profile</div>
        <div style="font-size:.8rem;color:var(--hx-text2);line-height:1.5;margin-bottom:10px">
          This grow has a dedicated Drying Room configured, so the 60/60 cure profile is managed
          entirely from the <strong style="color:var(--hx-text)">Drying</strong> tab instead of here.
          Zone 2's own exhaust still switches to gentle-cyclic airflow for the duration of the dry
          regardless of the dedicated room — its current status is shown below.
        </div>
        ${_dryingOverrideStatusHtml(d)}
      </div>` : `
      <div class="card">
        <div class="card-title">📊 ${stageMeta.icon} ${stageMeta.label} Profile ${isActiveStage ? '' : '<span class="badge bg-amber" style="margin-left:6px;font-size:.65rem">preview</span>'}</div>
        <div class="hx-period-toggle" style="display:flex;gap:6px;margin-bottom:12px">
          <button class="period-btn ${isDay ? 'active' : ''}" data-period="day"
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
            background:${isDay ? 'var(--hx-blue,#209cee)' : 'none'};color:${isDay ? '#fff' : 'var(--hx-text)'};font-weight:600">☀️ Day</button>
          <button class="period-btn ${!isDay ? 'active' : ''}" data-period="night"
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
            background:${!isDay ? 'var(--hx-blue,#209cee)' : 'none'};color:${!isDay ? '#fff' : 'var(--hx-text)'};font-weight:600">🌙 Night</button>
        </div>

        <div class="sec">VPD Range</div>
        <div style="margin-bottom:4px">
          ${_vpdBandSVG(vpdMin, vpdMax)}
        </div>
        <div class="slider-row">
          <span class="slider-lbl">Min</span>
          <input type="range" id="vpd-min-slider" min="0.3" max="1.8" step="0.05" value="${fn(vpdMin,2)}"/>
          <span class="slider-val" id="vpd-min-val">${fVPD(vpdMin)}</span>
        </div>
        <div class="slider-row">
          <span class="slider-lbl">Max</span>
          <input type="range" id="vpd-max-slider" min="0.3" max="1.8" step="0.05" value="${fn(vpdMax,2)}"/>
          <span class="slider-val" id="vpd-max-val">${fVPD(vpdMax)}</span>
        </div>

        <div class="sec">Temperature Anchor</div>
        <div class="slider-row">
          <input type="range" id="temp-anchor-slider" min="10" max="32" step="0.5" value="${fn(tempAnchor,1)}"/>
          <span class="slider-val" id="temp-anchor-val">${fT(tempAnchor)}</span>
        </div>
        <div style="font-size:.72rem;color:var(--hx-text2);margin:2px 0 10px" id="rh-guide-text">${rhGuideText}</div>

        <div class="g2">
          <div>
            <div class="sec">Light Intensity</div>
            <div class="slider-row">
              <input type="range" id="light-slider" min="0" max="100" step="1" value="${lightPct}"/>
              <span class="slider-val" id="light-val">${fPct(lightPct)}</span>
            </div>
          </div>
          <div>
            <div class="sec">Fan Speed</div>
            <div class="slider-row">
              <input type="range" id="fan-slider" min="0" max="100" step="1" value="${fanPct}"/>
              <span class="slider-val" id="fan-val">${fPct(fanPct)}</span>
            </div>
          </div>
        </div>
        <div class="metric-row" style="margin-top:6px">
          <span class="metric-label">Photoperiod</span>
          <span class="metric-val">${fn(photoperiod,1)} h <span style="font-size:.68rem;color:var(--hx-text2)">(from Growth Mode)</span></span>
        </div>

        <div class="sec">Stage Duration</div>
        <div class="slider-row">
          <input type="range" id="stage-duration-slider" min="1" max="70" step="1" value="${stageDuration}"/>
          <span class="slider-val" id="stage-duration-val">${stageDuration} day${stageDuration === 1 ? '' : 's'}</span>
        </div>
        <div style="font-size:.72rem;color:var(--hx-text2);margin:2px 0 10px" id="duration-guide-text">
          Typically ${durationGuidance} for ${growthModeCycle === 'autoflower' ? 'Autoflower' : 'Photoperiod'}
        </div>

        <div style="display:flex;align-items:center;gap:10px;margin-top:12px">
          <button id="save-stage-targets-btn" style="padding:9px 16px;border-radius:8px;border:none;
            background:var(--hx-blue,#209cee);color:#fff;font-weight:600;cursor:pointer">💾 Save Stage Targets</button>
          <span id="stage-save-status" style="font-size:.75rem;color:var(--hx-text2)"></span>
        </div>
        ${showDryingAirflowControls ? `
        <hr/>
        <div class="sec">60/60 Cure Profile</div>
        ${isDryingUnlocked
          ? `<div class="chip-row" style="margin-bottom:10px;align-items:center">
              <span class="badge bg-amber">🔓 Custom Profile Active (using the VPD/Temp above)</span>
              <button class="hx-relock-btn" style="margin-left:auto;padding:6px 10px;border-radius:8px;border:1px solid var(--hx-border,#333);background:none;color:var(--hx-text);cursor:pointer;font-size:.75rem">🔒 Re-lock to 60/60</button>
            </div>`
          : `<div class="chip-row" style="margin-bottom:10px;align-items:center">
              <span class="badge bg-blue">🔒 Locked: Standard Cure Profile — 15.5°C / 60% RH</span>
              <button class="hx-unlock-btn" style="margin-left:auto;padding:6px 10px;border-radius:8px;border:1px solid var(--hx-border,#333);background:none;color:var(--hx-text);cursor:pointer;font-size:.75rem">🔓 Unlock</button>
            </div>`}
        <div class="sec">Drying Airflow Mode</div>
        <div class="hx-period-toggle" style="display:flex;gap:6px;margin-bottom:8px">
          <button class="drying-airflow-btn ${dryingAirflowMode === 'constant' ? 'active' : ''}" data-mode="constant"
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
            background:${dryingAirflowMode === 'constant' ? 'var(--hx-blue,#209cee)' : 'none'};color:${dryingAirflowMode === 'constant' ? '#fff' : 'var(--hx-text)'};font-weight:600">Constant</button>
          <button class="drying-airflow-btn ${dryingAirflowMode === 'cyclic' ? 'active' : ''}" data-mode="cyclic"
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
            background:${dryingAirflowMode === 'cyclic' ? 'var(--hx-blue,#209cee)' : 'none'};color:${dryingAirflowMode === 'cyclic' ? '#fff' : 'var(--hx-text)'};font-weight:600">Cyclic</button>
        </div>
        <div style="font-size:.72rem;color:var(--hx-text2);margin-bottom:10px">
          Constant: gentle, steady airflow throughout the dry. Cyclic: alternates airflow on and off at set
          intervals — some growers prefer this to prevent one consistent air current from drying part of the
          canopy faster than the rest.
        </div>
        ${dryingAirflowMode === 'cyclic' ? `
        <div class="g2">
          <div>
            <div class="sec">Cycle On (min)</div>
            <input type="number" id="drying-cycle-on-input" min="1" step="1" value="${d.drying_cycle_on_min ?? 15}"
              style="width:100%;padding:6px;border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
          </div>
          <div>
            <div class="sec">Cycle Off (min)</div>
            <input type="number" id="drying-cycle-off-input" min="1" step="1" value="${d.drying_cycle_off_min ?? 15}"
              style="width:100%;padding:6px;border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
          </div>
        </div>` : ''}
        <hr/>
        ${_dryingOverrideStatusHtml(d)}
        ` : ''}
      </div>`}
      <!-- Progression mode -->
      <div class="card">
        <div class="card-title">⚙️ Progression Mode</div>
        <div class="toggle-row">
          <span class="toggle-lbl">Auto-Advance Stages (Timeframe Managed)</span>
          <label class="sw">
            <input type="checkbox" id="prog-toggle" ${progression === 'timeframe' ? 'checked' : ''}/>
            <span class="sw-track"></span>
            <span class="sw-thumb"></span>
          </label>
        </div>
        <div class="toggle-row">
          <span class="toggle-lbl">✦ Smooth Glides (interpolate VPD/light between stages)</span>
          <label class="sw">
            <input type="checkbox" id="glide-toggle" ${smoothGlides ? 'checked' : ''}/>
            <span class="sw-track"></span>
            <span class="sw-thumb"></span>
          </label>
        </div>
        <div class="sec">Stage-Progression Heads-Up Warning</div>
        <div class="slider-row">
          <span class="slider-lbl">Lead Time</span>
          <input type="range" id="stage-warning-lead-slider" min="1" max="14" step="1"
            value="${d.stage_warning_lead_days ?? 3}"/>
          <span class="slider-val" id="stage-warning-lead-val">${d.stage_warning_lead_days ?? 3} day${(d.stage_warning_lead_days ?? 3) === 1 ? '' : 's'}</span>
        </div>
        <div style="font-size:.7rem;color:var(--hx-text2);margin-top:2px">
          How many days before an expected stage transition to fire an informational reminder
          with manual-action suggestions (e.g. check trellis netting). Advisory only — Helix
          Cultivate never advances a stage automatically because of this.
        </div>
      </div>
      <!-- Abort Cycle (Part 1.5) — a second, clearly-distinct destructive
           action from harvest close-out: no harvest record, no weight
           entry, no journal archive. -->
      <div class="card" style="border:1px solid var(--hx-red,#ff5252)">
        <div class="card-title">⚠ Abort Cycle</div>
        <div style="font-size:.78rem;color:var(--hx-text2);margin-bottom:10px;line-height:1.5">
          For a cycle that never reaches harvest — pests, mistakes, or a failed run.
          This is <b>not</b> the same as closing out a real harvest: it discards the current
          stage/day-count with no weight entry and no harvest record, and returns to
          "No Active Cycle". If you actually have a harvest to record, use Close Out Harvest
          instead.
        </div>
        ${this._showAbortConfirm ? `
          <div style="background:rgba(255,82,82,.1);border-radius:8px;padding:10px;margin-bottom:10px;font-size:.8rem">
            Are you sure? This cannot be undone — the current cycle's stage and day-count
            will be lost.
          </div>
          <div style="display:flex;gap:8px">
            <button id="confirm-abort-btn" ${this._abortSaving ? 'disabled' : ''} style="flex:1;padding:10px;border-radius:8px;border:none;
              background:var(--hx-red,#ff5252);color:#fff;font-weight:700;cursor:pointer">
              ${this._abortSaving ? 'Aborting…' : 'Yes, Abort This Cycle'}
            </button>
            <button id="cancel-abort-btn" style="flex:1;padding:10px;border-radius:8px;border:1px solid var(--hx-border);
              background:none;color:var(--hx-text);cursor:pointer">Cancel</button>
          </div>
        ` : `
          <button id="open-abort-confirm-btn" style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--hx-red,#ff5252);
            background:none;color:var(--hx-red,#ff5252);font-weight:700;cursor:pointer">⚠ Abort Cycle…</button>
        `}
      </div>
      <!-- Recipe export / import -->
      <div class="card">
        <div class="card-title">📋 Recipe Sharing</div>
        <div style="display:flex;gap:8px">
          <button id="export-recipe-btn" style="flex:1;padding:10px;border-radius:8px;border:1px solid var(--hx-border);
            background:none;color:var(--hx-text);cursor:pointer">📋 Export Recipe</button>
          <button id="import-recipe-btn" style="flex:1;padding:10px;border-radius:8px;border:1px solid var(--hx-border);
            background:none;color:var(--hx-text);cursor:pointer">📥 Import Recipe</button>
        </div>
        ${this._showExportModal ? `
          <div class="sec">Export YAML (copy below)</div>
          <textarea id="export-yaml-textarea" readonly style="width:100%;min-height:220px;font-family:monospace;
            font-size:.72rem;padding:8px;border-radius:8px;border:1px solid var(--hx-border);
            background:var(--hx-surface2);color:var(--hx-text)">${this._exportYaml}</textarea>
          <button id="close-export-modal-btn" style="margin-top:8px;width:100%;padding:8px;border-radius:8px;
            border:1px solid var(--hx-border);background:none;color:var(--hx-text);cursor:pointer">Close</button>
        ` : ''}
        ${this._showImportModal ? `
          <div class="sec">Paste Recipe YAML</div>
          ${this._importError ? `<div class="badge bg-red" style="margin-bottom:6px">${this._importError}</div>` : ''}
          <textarea id="import-yaml-textarea" style="width:100%;min-height:220px;font-family:monospace;
            font-size:.72rem;padding:8px;border-radius:8px;border:1px solid var(--hx-border);
            background:var(--hx-surface2);color:var(--hx-text)" placeholder="stages:\n  germination:\n    duration_days: 7\n    ..."></textarea>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button id="apply-import-btn" style="flex:1;padding:8px;border-radius:8px;border:none;
              background:var(--hx-green,#3ecf6a);color:#fff;font-weight:700;cursor:pointer">Validate &amp; Apply</button>
            <button id="cancel-import-btn" style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border);
              background:none;color:var(--hx-text);cursor:pointer">Cancel</button>
          </div>
        ` : ''}
      </div>`;

    // Stage select from timeline
    this.shadowRoot.querySelectorAll('[data-stage]').forEach(el => {
      el.addEventListener('click', () => {
        this._editingStage = el.dataset.stage;
        this._render();
      });
    });

    // Day/Night period toggle
    this.shadowRoot.querySelectorAll('.period-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._editingPeriod = btn.dataset.period;
        this._render();
      });
    });

    // Everything below queries elements that only exist in the full profile
    // editor card — skipped entirely when the Drying notice card replaced it.
    if (!dryingHiddenNotice) {
    // Refresh the RH guide text live as the sliders move
    const refreshRhGuide = () => {
      const t = parseFloat(this.shadowRoot.querySelector('#temp-anchor-slider').value);
      const vMin = parseFloat(this.shadowRoot.querySelector('#vpd-min-slider').value);
      const vMax = parseFloat(this.shadowRoot.querySelector('#vpd-max-slider').value);
      const lo = _rhGuideForVpd(t, vMax);
      const hi = _rhGuideForVpd(t, vMin);
      const el = this.shadowRoot.querySelector('#rh-guide-text');
      if (el) el.textContent = (lo != null && hi != null) ? `Guide: ~${fn(lo,0)}–${fn(hi,0)}% RH at ${fn(t,1)}°C` : '—';
    };

    // VPD min slider
    const vpdMinSl = this.shadowRoot.querySelector('#vpd-min-slider');
    const vpdMinVal = this.shadowRoot.querySelector('#vpd-min-val');
    vpdMinSl.addEventListener('input', e => {
      vpdMinVal.textContent = fVPD(parseFloat(e.target.value));
      refreshRhGuide();
    });
    // Stage-target persistence now happens only via the explicit "Save Stage
    // Targets" button (bound below) — sliders no longer auto-save per change,
    // which previously relied on a draft object that didn't survive this
    // element being destroyed/recreated on tab switches. vpd_target is
    // derived server-side as the midpoint of the persisted day/night VPD
    // range (see coordinator.py's smooth-glide tick), so the VPD min/max
    // sliders never push directly to a live number entity either way.

    // VPD max slider
    const vpdMaxSl = this.shadowRoot.querySelector('#vpd-max-slider');
    const vpdMaxVal = this.shadowRoot.querySelector('#vpd-max-val');
    vpdMaxSl.addEventListener('input', e => {
      vpdMaxVal.textContent = fVPD(parseFloat(e.target.value));
      refreshRhGuide();
    });

    // Temp anchor slider — v1.5.0: no longer pushes a "live preview" to
    // number.helix_cultivate_temp_setpoint on change. That entity now
    // feeds the day/night-keyed Temporary Override system (Part 4), so a
    // preview push here would leave a stale override in place that could
    // shadow this exact slider's own "Save Stage Targets" click (Part 5
    // requires the permanent save to take effect immediately, unshadowed).
    const tempSl = this.shadowRoot.querySelector('#temp-anchor-slider');
    const tempVal = this.shadowRoot.querySelector('#temp-anchor-val');
    tempSl.addEventListener('input', e => {
      tempVal.textContent = fT(parseFloat(e.target.value));
      refreshRhGuide();
    });

    // Light slider — same reasoning as the temp anchor above.
    const lightSl = this.shadowRoot.querySelector('#light-slider');
    const lightVal = this.shadowRoot.querySelector('#light-val');
    lightSl.addEventListener('input', e => { lightVal.textContent = fPct(parseFloat(e.target.value)); });

    // Fan speed slider
    const fanSl = this.shadowRoot.querySelector('#fan-slider');
    const fanVal = this.shadowRoot.querySelector('#fan-val');
    fanSl.addEventListener('input', e => { fanVal.textContent = fPct(parseFloat(e.target.value)); });

    // Stage duration slider (Part 3.1)
    const durationSl = this.shadowRoot.querySelector('#stage-duration-slider');
    const durationVal = this.shadowRoot.querySelector('#stage-duration-val');
    if (durationSl) {
      durationSl.addEventListener('input', e => {
        const v = parseInt(e.target.value, 10);
        if (durationVal) durationVal.textContent = `${v} day${v === 1 ? '' : 's'}`;
      });
    }

    // Growth Mode toggle (Part 1.1) — immediate write, same config value
    // as Primary Grow Space's own copy of this toggle.
    this.shadowRoot.querySelectorAll('.cycle-growth-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.disabled) return;
        this._setGrowthMode(btn.dataset.mode);
      });
    });

    // Explicit Save — reads every slider above straight from the DOM.
    const saveStageBtn = this.shadowRoot.querySelector('#save-stage-targets-btn');
    if (saveStageBtn) {
      saveStageBtn.addEventListener('click', () => {
        this._saveStageTargetsFromDom(stage, isDay);
      });
    }

    // Drying-without-a-dedicated-room extras (2.A5 / 2.B1): 60/60 lock toggle
    // and constant/cyclic airflow mode — only present when showDryingAirflowControls.
    if (showDryingAirflowControls) {
      const entryId = (this._data || {}).entry_id;
      const unlockBtn = this.shadowRoot.querySelector('.hx-unlock-btn');
      if (unlockBtn) unlockBtn.addEventListener('click', async () => {
        if (!this._hass || !entryId) return;
        try {
          await this._hass.callWS({ type: 'helix_cultivate/toggle_drying_lock', entry_id: entryId, unlocked: true });
          this._data = { ...this._data, is_drying_unlocked: true };
          this._render();
        } catch (e) { console.error('Helix Cultivate: drying lock toggle failed', e); }
      });
      const relockBtn = this.shadowRoot.querySelector('.hx-relock-btn');
      if (relockBtn) relockBtn.addEventListener('click', async () => {
        if (!this._hass || !entryId) return;
        try {
          await this._hass.callWS({ type: 'helix_cultivate/toggle_drying_lock', entry_id: entryId, unlocked: false });
          this._data = { ...this._data, is_drying_unlocked: false };
          this._render();
        } catch (e) { console.error('Helix Cultivate: drying lock toggle failed', e); }
      });

      const saveDryingField = async (fields) => {
        if (!this._hass || !entryId) return;
        try {
          await this._hass.callWS({ type: 'helix_cultivate/update_settings_fields', entry_id: entryId, fields });
        } catch (e) { console.error('Helix Cultivate: drying airflow save failed', e); }
      };

      this.shadowRoot.querySelectorAll('.drying-airflow-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          saveDryingField({ drying_airflow_mode: btn.dataset.mode });
          this._data = { ...this._data, drying_airflow_mode: btn.dataset.mode };
          this._render();
        });
      });

      const cycleOnEl = this.shadowRoot.querySelector('#drying-cycle-on-input');
      if (cycleOnEl) cycleOnEl.addEventListener('change', e => {
        saveDryingField({ drying_cycle_on_min: parseFloat(e.target.value) });
      });
      const cycleOffEl = this.shadowRoot.querySelector('#drying-cycle-off-input');
      if (cycleOffEl) cycleOffEl.addEventListener('change', e => {
        saveDryingField({ drying_cycle_off_min: parseFloat(e.target.value) });
      });
    }
    }

    // Progression toggle
    const progToggle = this.shadowRoot.querySelector('#prog-toggle');
    progToggle.addEventListener('change', e => {
      this._callService('select', 'select_option', {
        entity_id: 'select.helix_cultivate_progression_mode',
        option: e.target.checked ? 'timeframe' : 'manual'
      });
    });

    // Smooth glides
    const glideToggle = this.shadowRoot.querySelector('#glide-toggle');
    glideToggle.addEventListener('change', e => {
      this._callService('switch', e.target.checked ? 'turn_on' : 'turn_off', {
        entity_id: 'switch.helix_cultivate_smooth_glides'
      });
    });

    // ── Harvest close-out bindings ────────────────────────────────────────────
    const openHarvestBtn = this.shadowRoot.querySelector('#open-harvest-form-btn');
    if (openHarvestBtn) openHarvestBtn.addEventListener('click', () => {
      this._showHarvestForm = true;
      this._harvestError = null;
      this._render();
    });

    const cancelHarvestBtn = this.shadowRoot.querySelector('#cancel-harvest-btn');
    if (cancelHarvestBtn) cancelHarvestBtn.addEventListener('click', () => {
      this._showHarvestForm = false;
      this._harvestError = null;
      this._render();
    });

    const archiveHarvestBtn = this.shadowRoot.querySelector('#archive-harvest-btn');
    if (archiveHarvestBtn) archiveHarvestBtn.addEventListener('click', () => {
      const wetEl = this.shadowRoot.querySelector('#wet-weight-input');
      const dryEl = this.shadowRoot.querySelector('#dry-weight-input');
      const wet = parseFloat(wetEl.value);
      const dry = parseFloat(dryEl.value);
      if (isNaN(wet) || isNaN(dry)) {
        this._harvestError = 'Enter valid wet and dry weights';
        this._render();
        return;
      }
      this._submitHarvest(wet, dry);
    });

    const closeReportBtn = this.shadowRoot.querySelector('#close-harvest-report-btn');
    if (closeReportBtn) closeReportBtn.addEventListener('click', () => this._closeHarvestReport());

    // ── Recipe export / import bindings ───────────────────────────────────────
    const exportBtn = this.shadowRoot.querySelector('#export-recipe-btn');
    if (exportBtn) exportBtn.addEventListener('click', () => this._openExportModal());

    const closeExportBtn = this.shadowRoot.querySelector('#close-export-modal-btn');
    if (closeExportBtn) closeExportBtn.addEventListener('click', () => {
      this._showExportModal = false;
      this._render();
    });

    const importBtn = this.shadowRoot.querySelector('#import-recipe-btn');
    if (importBtn) importBtn.addEventListener('click', () => {
      this._showImportModal = true;
      this._importError = null;
      this._render();
    });

    const cancelImportBtn = this.shadowRoot.querySelector('#cancel-import-btn');
    if (cancelImportBtn) cancelImportBtn.addEventListener('click', () => {
      this._showImportModal = false;
      this._render();
    });

    const applyImportBtn = this.shadowRoot.querySelector('#apply-import-btn');
    if (applyImportBtn) applyImportBtn.addEventListener('click', () => {
      const ta = this.shadowRoot.querySelector('#import-yaml-textarea');
      this._submitImport(ta.value);
    });

    // Stage-progression warning lead time (Part 3)
    const warnSl = this.shadowRoot.querySelector('#stage-warning-lead-slider');
    const warnVal = this.shadowRoot.querySelector('#stage-warning-lead-val');
    if (warnSl) {
      warnSl.addEventListener('input', e => {
        const v = parseInt(e.target.value, 10);
        if (warnVal) warnVal.textContent = `${v} day${v === 1 ? '' : 's'}`;
      });
      warnSl.addEventListener('change', async e => {
        const entryId = (this._data || {}).entry_id;
        if (!this._hass || !entryId) return;
        try {
          await this._hass.callWS({
            type: 'helix_cultivate/update_settings_fields',
            entry_id: entryId,
            fields: { stage_warning_lead_days: parseInt(e.target.value, 10) },
          });
        } catch (err) {
          console.error('Helix Cultivate: stage_warning_lead_days save failed', err);
        }
      });
    }

    // Abort Cycle (Part 1.5)
    const openAbortBtn = this.shadowRoot.querySelector('#open-abort-confirm-btn');
    if (openAbortBtn) openAbortBtn.addEventListener('click', () => {
      this._showAbortConfirm = true;
      this._render();
    });
    const cancelAbortBtn = this.shadowRoot.querySelector('#cancel-abort-btn');
    if (cancelAbortBtn) cancelAbortBtn.addEventListener('click', () => {
      this._showAbortConfirm = false;
      this._render();
    });
    const confirmAbortBtn = this.shadowRoot.querySelector('#confirm-abort-btn');
    if (confirmAbortBtn) confirmAbortBtn.addEventListener('click', () => this._doAbortCycle());

    this._bindSpaceEmptyAndDryingHarvest();
  }

  async _doAbortCycle() {
    if (!this._hass) return;
    this._abortSaving = true;
    this._render();
    try {
      await this._hass.callWS({ type: 'helix_cultivate/abort_cycle' });
      this._showAbortConfirm = false;
      // The abort triggers a config-entry reload (same as other explicit
      // lifecycle actions) — the next coordinator data push naturally
      // reflects cycle_state === 'not_started', so no manual state patch
      // is needed here beyond closing the confirm dialog.
    } catch (e) {
      console.error('Helix Cultivate: abort_cycle failed', e);
    } finally {
      this._abortSaving = false;
      this._render();
    }
  }

  // ── Space Now Empty (Part 4.2) ────────────────────────────────────────────

  _bindSpaceEmptyAndDryingHarvest() {
    const openSpaceEmptyBtn = this.shadowRoot.querySelector('#open-space-empty-btn');
    if (openSpaceEmptyBtn) openSpaceEmptyBtn.addEventListener('click', () => {
      this._showSpaceEmptyConfirm = true;
      this._render();
    });
    const cancelSpaceEmptyBtn = this.shadowRoot.querySelector('#cancel-space-empty-btn');
    if (cancelSpaceEmptyBtn) cancelSpaceEmptyBtn.addEventListener('click', () => {
      this._showSpaceEmptyConfirm = false;
      this._render();
    });
    const confirmSpaceEmptyBtn = this.shadowRoot.querySelector('#confirm-space-empty-btn');
    if (confirmSpaceEmptyBtn) confirmSpaceEmptyBtn.addEventListener('click', async () => {
      if (!this._hass) return;
      this._spaceEmptySaving = true;
      this._render();
      try {
        await this._hass.callWS({ type: 'helix_cultivate/space_now_empty' });
        this._showSpaceEmptyConfirm = false;
        const panel = this.closest('helix-panel');
        if (panel && typeof panel._update === 'function') panel._update();
      } catch (e) {
        console.error('Helix Cultivate: space_now_empty failed', e);
      } finally {
        this._spaceEmptySaving = false;
        this._render();
      }
    });

    // Harvest Complete — Drying Room (Part 9)
    const openDryingHarvestBtn = this.shadowRoot.querySelector('#open-drying-harvest-form-btn');
    if (openDryingHarvestBtn) openDryingHarvestBtn.addEventListener('click', () => {
      this._showDryingHarvestForm = true;
      this._render();
    });
    const cancelDryingHarvestBtn = this.shadowRoot.querySelector('#cancel-drying-harvest-btn');
    if (cancelDryingHarvestBtn) cancelDryingHarvestBtn.addEventListener('click', () => {
      this._showDryingHarvestForm = false;
      this._render();
    });
    this.shadowRoot.querySelectorAll('.drying-harvest-unit-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._dryingHarvestUnit = btn.dataset.unit;
        this._render();
      });
    });
    const archiveDryingHarvestBtn = this.shadowRoot.querySelector('#archive-drying-harvest-btn');
    if (archiveDryingHarvestBtn) archiveDryingHarvestBtn.addEventListener('click', async () => {
      const wetInput = this.shadowRoot.querySelector('#drying-wet-weight-input');
      const dryInput = this.shadowRoot.querySelector('#drying-dry-weight-input');
      const wetRaw = parseFloat(wetInput ? wetInput.value : '');
      const dryRaw = parseFloat(dryInput ? dryInput.value : '');
      if (!(wetRaw >= 0) || !(dryRaw >= 0)) {
        this._dryingHarvestError = 'Enter valid wet and dry weights.';
        this._render();
        return;
      }
      // Part 9.1: canonical stored unit is grams regardless of entry unit.
      const OZ_TO_G = 28.3495;
      const wetWeightG = this._dryingHarvestUnit === 'oz' ? wetRaw * OZ_TO_G : wetRaw;
      const dryWeightG = this._dryingHarvestUnit === 'oz' ? dryRaw * OZ_TO_G : dryRaw;
      if (!this._hass) return;
      this._dryingHarvestError = null;
      try {
        const result = await this._hass.callWS({
          type: 'helix_cultivate/harvest_complete_drying_batch',
          wet_weight_g: wetWeightG,
          dry_weight_g: dryWeightG,
        });
        this._dryingHarvestReport = result;
        this._showDryingHarvestForm = false;
        this._render();
      } catch (e) {
        this._dryingHarvestError = (e && e.message) || 'Failed to archive this batch';
        this._render();
      }
    });
    const closeDryingHarvestReportBtn = this.shadowRoot.querySelector('#close-drying-harvest-report-btn');
    if (closeDryingHarvestReportBtn) closeDryingHarvestReportBtn.addEventListener('click', () => {
      this._dryingHarvestReport = null;
      this._render();
      const panel = this.closest('helix-panel');
      if (panel && typeof panel._update === 'function') panel._update();
    });
  }

  // ── Start New Cycle (Part 1.2 / 1.3) ──────────────────────────────────────

  _renderNoActiveCycle() {
    const targetableStages = Object.keys(STAGE_META).filter(s => s !== 'drying');
    this.shadowRoot.innerHTML = `
      <style>${BASE_CSS}:host{display:block;}</style>
      <div class="card">
        <div style="text-align:center;padding:20px 10px 24px">
          <div style="font-size:2.4rem;margin-bottom:8px">🌱</div>
          <div style="font-size:1.2rem;font-weight:800;margin-bottom:6px">No Active Cycle</div>
          <div style="font-size:.85rem;color:var(--hx-text2);max-width:420px;margin:0 auto;line-height:1.5">
            Start a new cycle to begin day-counting, stage progression, and environmental
            control targets.
          </div>
        </div>
        <div class="sec">Growth Mode</div>
        <div style="display:flex;gap:6px;margin-bottom:14px">
          <button class="start-growth-mode-btn ${this._startGrowthMode === 'photoperiod' ? 'active' : ''}" data-mode="photoperiod"
            style="flex:1;padding:10px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
            background:${this._startGrowthMode === 'photoperiod' ? 'var(--hx-blue,#209cee)' : 'none'};
            color:${this._startGrowthMode === 'photoperiod' ? '#fff' : 'var(--hx-text)'};font-weight:600">Photoperiod</button>
          <button class="start-growth-mode-btn ${this._startGrowthMode === 'autoflower' ? 'active' : ''}" data-mode="autoflower"
            style="flex:1;padding:10px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
            background:${this._startGrowthMode === 'autoflower' ? 'var(--hx-blue,#209cee)' : 'none'};
            color:${this._startGrowthMode === 'autoflower' ? '#fff' : 'var(--hx-text)'};font-weight:600">Autoflower</button>
        </div>
        <div class="sec">Start Date</div>
        <div style="margin-bottom:14px">
          <input type="date" id="start-cycle-date" value="${this._startDate}"
            style="padding:8px;border-radius:8px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
          <div style="font-size:.7rem;color:var(--hx-text2);margin-top:4px">
            Backdate this if the plant was already a few days old when you set up the
            integration — day-counting and stage duration will be calculated from this date.
          </div>
        </div>
        <div class="sec">Starting Stage</div>
        <div style="margin-bottom:16px">
          <select id="start-cycle-stage" style="width:100%;padding:8px;border-radius:8px;
            border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)">
            ${targetableStages.map(s => `<option value="${s}" ${this._startStage === s ? 'selected' : ''}>${STAGE_META[s].icon} ${STAGE_META[s].label}</option>`).join('')}
          </select>
          <div style="font-size:.7rem;color:var(--hx-text2);margin-top:4px">
            Defaults to Germination — choose further along (e.g. Early Veg) for clones or
            plants purchased already established.
          </div>
        </div>
        ${this._startError ? `<div class="badge bg-red" style="margin-bottom:10px">${this._startError}</div>` : ''}
        <button id="submit-start-cycle-btn" ${this._startSaving ? 'disabled' : ''} style="width:100%;padding:12px;border-radius:10px;border:none;
          background:var(--hx-accent);color:#fff;font-weight:700;cursor:pointer;font-size:.9rem">
          ${this._startSaving ? 'Starting…' : '🌱 Start New Cycle'}
        </button>
      </div>`;

    this.shadowRoot.querySelectorAll('.start-growth-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._startGrowthMode = btn.dataset.mode;
        this._render();
      });
    });
    const dateInput = this.shadowRoot.querySelector('#start-cycle-date');
    if (dateInput) dateInput.addEventListener('change', e => { this._startDate = e.target.value; });
    const stageSelect = this.shadowRoot.querySelector('#start-cycle-stage');
    if (stageSelect) stageSelect.addEventListener('change', e => { this._startStage = e.target.value; });

    const submitBtn = this.shadowRoot.querySelector('#submit-start-cycle-btn');
    if (submitBtn) submitBtn.addEventListener('click', () => this._doStartCycle());
  }

  async _doStartCycle() {
    if (!this._hass) return;
    this._startError = null;
    this._startSaving = true;
    this._render();
    try {
      await this._hass.callWS({
        type: 'helix_cultivate/start_cycle',
        growth_mode: this._startGrowthMode,
        start_date: this._startDate,
        starting_stage: this._startStage,
      });
      // Config-entry reload follows (same as other explicit lifecycle
      // actions) — the next coordinator data push reflects
      // cycle_state === 'active' with the new stage/date, so no manual
      // state patch is needed here.
    } catch (e) {
      console.error('Helix Cultivate: start_cycle failed', e);
      this._startError = e?.message || 'Could not start cycle — see console';
    } finally {
      this._startSaving = false;
      this._render();
    }
  }

  connectedCallback() { this._render(); }
}
customElements.define('helix-tab-cycle', HelixTabCycle);

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Primary Grow Space  <helix-tab-growspace>
// ─────────────────────────────────────────────────────────────────────────────

// ── Zone hardware-picker key definitions ──────────────────────────────────────

// Part 6 (v1.4.0) hardware-mapping reorder — pure layout, no config-key or
// mapping changes. Sensors stay first (6.1). exhaust_fan, zone2_grow_light,
// and dli_sensor are marked `manualPlacement: true` and rendered
// individually elsewhere in the form (6.2/6.3 — Exhaust Fan gets its own
// heading immediately above Circulation Fan Mapping; Grow Light/DLI Sensor
// move into the Fixture Type section) rather than in this flat generic
// block — but they stay in this array (and are still passed to
// _bindHwPicker) so domain-filtering and entity-picker binding work
// identically regardless of where their .hw-entity-slot ends up in the DOM.
const ZONE2_HW_KEYS = [
  { key: 'upper_canopy_temp_sensor',     label: 'Upper Canopy Temp',      domains: ['sensor'] },
  { key: 'upper_canopy_humidity_sensor', label: 'Upper Canopy Humidity',  domains: ['sensor'] },
  { key: 'mid_canopy_temp_sensor',       label: 'Mid Canopy Temp',        domains: ['sensor'] },
  { key: 'mid_canopy_humidity_sensor',   label: 'Mid Canopy Humidity',    domains: ['sensor'] },
  { key: 'lower_canopy_temp_sensor',     label: 'Lower Canopy Temp',      domains: ['sensor'] },
  { key: 'lower_canopy_humidity_sensor', label: 'Lower Canopy Humidity',  domains: ['sensor'] },
  { key: 'zone2_ac',                     label: 'Zone 2 AirCon',          domains: ['climate', 'switch'], reverseCycleToggle: 'zone2_is_reverse_cycle' },
  { key: 'zone2_heater',                 label: 'Zone 2 Heater',          domains: ['switch', 'climate'] },
  { key: 'zone2_humidifier',             label: 'Zone 2 Humidifier',      domains: ['switch', 'climate'] },
  { key: 'zone2_dehumidifier',           label: 'Zone 2 Dehumidifier',    domains: ['switch', 'climate'] },
  { key: 'exhaust_fan',                  label: 'Exhaust Fan',            domains: ['fan', 'switch'], manualPlacement: true },
  { key: 'zone2_grow_light',             label: 'Grow Light',             domains: ['light', 'switch'], manualPlacement: true },
  { key: 'dli_sensor',                   label: 'DLI / PAR Sensor',       domains: ['sensor'], manualPlacement: true },
];

// Rendered in its own "Supplemental Lighting" sub-section (see
// HelixTabGrowspace's hw-edit branch) rather than the flat ZONE2_HW_KEYS
// list above, but still merged into the array passed to _bindHwPicker so
// its entity picker gets the same domain filtering as every other slot.
const ZONE2_SUPPLEMENTAL_HW_KEY = {
  key: 'zone2_supplemental_light', label: 'Supplemental Light', domains: ['light', 'switch'],
};

const ZONE1_HW_KEYS = [
  { key: 'lung_temp_sensor',     label: 'Conditioning Room Temp',     domains: ['sensor'] },
  { key: 'lung_humidity_sensor', label: 'Conditioning Room Humidity', domains: ['sensor'] },
  { key: 'zone1_ac',             label: 'Zone 1 AirCon',              domains: ['climate', 'switch'], reverseCycleToggle: 'zone1_is_reverse_cycle' },
  { key: 'zone1_heater',         label: 'Zone 1 Heater',              domains: ['switch', 'climate'] },
  { key: 'zone1_humidifier',     label: 'Zone 1 Humidifier',          domains: ['switch', 'climate'] },
  { key: 'zone1_dehumidifier',   label: 'Zone 1 Dehumidifier',        domains: ['switch', 'climate'] },
  { key: 'zone1_backup_heater',  label: 'Zone 1 Backup Heater',       domains: ['switch'] },
];

const DRYING_HW_KEYS = [
  { key: 'drying_temp_sensor',     label: 'Drying Room Temp',       domains: ['sensor'] },
  { key: 'drying_humidity_sensor', label: 'Drying Room Humidity',   domains: ['sensor'] },
  { key: 'drying_exhaust_fan',     label: 'Drying Exhaust Fan',     domains: ['fan', 'switch'] },
  { key: 'drying_circulation_fan', label: 'Drying Circulation Fan', domains: ['fan', 'switch'] },
  { key: 'drying_dehumidifier',    label: 'Drying Dehumidifier',    domains: ['switch', 'climate'] },
  { key: 'drying_ac',              label: 'Drying AirCon',          domains: ['climate', 'switch'], reverseCycleToggle: 'drying_is_reverse_cycle' },
  { key: 'drying_heater',          label: 'Drying Heater',          domains: ['switch', 'climate'] },
  { key: 'drying_light',           label: 'Inspection Light',       domains: ['light', 'switch'] },
];

// Energy & ROI — 4 EM sensor slots per zone. Each is a plain wattage sensor
// (not an appliance to switch), so 'sensor' is the only valid domain.
const ENERGY_ZONE2_EM_KEYS = [
  { key: 'em_zone2_s1', label: 'Slot 1', domains: ['sensor'] },
  { key: 'em_zone2_s2', label: 'Slot 2', domains: ['sensor'] },
  { key: 'em_zone2_s3', label: 'Slot 3', domains: ['sensor'] },
  { key: 'em_zone2_s4', label: 'Slot 4', domains: ['sensor'] },
];
const ENERGY_ZONE1_EM_KEYS = [
  { key: 'em_zone1_s1', label: 'Slot 1', domains: ['sensor'] },
  { key: 'em_zone1_s2', label: 'Slot 2', domains: ['sensor'] },
  { key: 'em_zone1_s3', label: 'Slot 3', domains: ['sensor'] },
  { key: 'em_zone1_s4', label: 'Slot 4', domains: ['sensor'] },
];
const ENERGY_DRYING_EM_KEYS = [
  { key: 'em_drying_s1', label: 'Slot 1', domains: ['sensor'] },
  { key: 'em_drying_s2', label: 'Slot 2', domains: ['sensor'] },
  { key: 'em_drying_s3', label: 'Slot 3', domains: ['sensor'] },
  { key: 'em_drying_s4', label: 'Slot 4', domains: ['sensor'] },
];
const ENERGY_GLOBAL_EM_KEYS = [
  { key: 'em_global_s1', label: 'Slot 1', domains: ['sensor'] },
  { key: 'em_global_s2', label: 'Slot 2', domains: ['sensor'] },
  { key: 'em_global_s3', label: 'Slot 3', domains: ['sensor'] },
  { key: 'em_global_s4', label: 'Slot 4', domains: ['sensor'] },
];
const ENERGY_ALL_EM_KEYS = [
  ...ENERGY_ZONE2_EM_KEYS, ...ENERGY_ZONE1_EM_KEYS,
  ...ENERGY_DRYING_EM_KEYS, ...ENERGY_GLOBAL_EM_KEYS,
];

function _entitiesForDomains(hass, domains) {
  if (!hass || !hass.states) return [];
  return Object.keys(hass.states)
    .filter(id => domains.includes(id.split('.')[0]))
    .sort();
}

// Detection guard — ha-entity-picker is provided by the HA frontend bundle
// (available because manifest.json declares "dependencies": ["frontend"]).
function _hasEntityPicker() {
  return Boolean(customElements.get('ha-entity-picker'));
}

// Build the interactive entity-picker element for a single hardware slot.
// Prefers the native ha-entity-picker (searchable, domain-filtered) and
// falls back to a filterable <select> + text <input> when unavailable.
function _entityPickerEl(keyDef, currentVal, hass, onChange) {
  if (_hasEntityPicker()) {
    const el = document.createElement('ha-entity-picker');
    el.hass = hass;
    el.value = currentVal || '';
    el.includeDomains = keyDef.domains;
    el.allowCustomEntity = false;
    el.style.display = 'block';
    el.addEventListener('value-changed', e => onChange(e.detail.value || null));
    return el;
  }
  // Fallback: filterable <select> with live substring search <input>
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:4px';

  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = 'Filter entities…';
  input.style.cssText =
    'padding:6px;border-radius:6px;background:var(--hx-card2,#1a1a1a);' +
    'color:var(--hx-text);border:1px solid var(--hx-border,#333);font-size:.75rem';

  const sel = document.createElement('select');
  sel.style.cssText =
    'padding:7px;border-radius:6px;background:var(--hx-card2,#1a1a1a);' +
    'color:var(--hx-text);border:1px solid var(--hx-border,#333)';

  const options = _entitiesForDomains(hass, keyDef.domains);
  const populate = (filterText = '') => {
    const needle = filterText.trim().toLowerCase();
    const filtered = needle ? options.filter(id => id.toLowerCase().includes(needle)) : options;
    sel.innerHTML = ['<option value="">— None —</option>']
      .concat(filtered.map(id => `<option value="${id}" ${id === currentVal ? 'selected' : ''}>${id}</option>`))
      .join('');
  };
  populate();
  input.addEventListener('input', () => populate(input.value));
  sel.addEventListener('change', () => onChange(sel.value || null));

  wrap.append(input, sel);
  return wrap;
}

function _hwPickerRow(keyDef, currentVal, toggleDef = null) {
  // Part 5.2: an optional Reverse Cycle toggle rendered directly beside its
  // AirCon entity picker — one physical device, one entity slot; the
  // toggle only changes how that same mapped entity is controlled.
  const toggleHtml = toggleDef ? _hwLayerToggleRow(toggleDef.key, toggleDef.label, toggleDef.checked) : '';
  return `
    <div class="hw-row" style="display:flex;flex-direction:column;gap:2px;margin-bottom:10px">
      <label style="font-size:.75rem;color:var(--hx-text2)">${keyDef.label}</label>
      <div class="hw-entity-slot" data-key="${keyDef.key}" data-current="${currentVal || ''}"></div>
      ${toggleHtml}
    </div>`;
}

function _hwLayerToggleRow(dataLayer, label, checked) {
  return `
    <div class="toggle-row">
      <span class="toggle-lbl">${label}</span>
      <label class="sw">
        <input type="checkbox" class="hw-layer-toggle" data-layer="${dataLayer}" ${checked ? 'checked' : ''}/>
        <span class="sw-track"></span>
        <span class="sw-thumb"></span>
      </label>
    </div>`;
}

// ── Canopy circulation fan mapping (Part 3) ────────────────────────────────
// Each tier stores up to 4 fan entity IDs as a single list
// (upper_fans/mid_fans/lower_fans — matching CONF_UPPER_FANS etc., already
// consumed by coordinator._get_tier_fans()/_apply_fan_speed_to_tier(), which
// already drive every entity in the list simultaneously). The count selector
// is pure local UI state — it just shows/hides slot rows via plain DOM
// toggling (never a form rebuild, so in-progress picker selections in other
// slots/sections are never disturbed) — and determines how many of the 4
// slots are actually submitted on Save.
const CANOPY_FAN_TIERS = [
  { tier: 'upper', label: 'Upper Canopy', confKey: 'upper_fans' },
  { tier: 'mid',   label: 'Mid Canopy',   confKey: 'mid_fans' },
  { tier: 'lower', label: 'Lower Canopy', confKey: 'lower_fans' },
];

function _canopyFanTierSectionHtml(tier, label, currentFans) {
  const fans = (currentFans || []).concat([null, null, null, null]).slice(0, 4);
  const count = fans.filter(Boolean).length;
  const rows = fans.map((val, i) => `
    <div class="hw-row canopy-fan-slot-row" data-tier="${tier}" data-slot="${i}" ${i >= count ? 'hidden' : ''}
      style="display:flex;flex-direction:column;gap:2px;margin-bottom:10px">
      <label style="font-size:.75rem;color:var(--hx-text2)">Fan ${i + 1}</label>
      <div class="canopy-fan-entity-slot" data-tier="${tier}" data-slot="${i}" data-current="${val || ''}"></div>
    </div>`).join('');
  return `
    <div class="sec">${label} Fans</div>
    <div class="metric-row" style="margin-bottom:8px">
      <span class="metric-label">Fan Count</span>
      <select class="canopy-fan-count-select" data-tier="${tier}" style="padding:6px;border-radius:6px;
        border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)">
        ${[0, 1, 2, 3, 4].map(n => `<option value="${n}" ${n === count ? 'selected' : ''}>${n}</option>`).join('')}
      </select>
    </div>
    <div class="canopy-fan-slots" data-tier="${tier}">${rows}</div>`;
}

function _renderCanopyFanMappingSection(d) {
  const hwMap = d.hw_map || {};
  return `
    <div class="sec">🌀 Circulation Fan Mapping</div>
    <div style="font-size:.72rem;color:var(--hx-text2);margin-bottom:8px">
      Map up to 4 fan entities per canopy tier — all are driven to the same
      speed simultaneously (breeze variance and wind sweep apply per-tier,
      not per-fan).
    </div>
    ${CANOPY_FAN_TIERS.map(t => _canopyFanTierSectionHtml(t.tier, t.label, hwMap[t.confKey])).join('')}`;
}

function _bindCanopyFanMappingSection(shadowRoot, hostEl) {
  hostEl._canopyFanSlotValues = hostEl._canopyFanSlotValues || {};
  CANOPY_FAN_TIERS.forEach(({ tier, confKey }) => {
    const slotValues = shadowRoot.querySelectorAll(`.canopy-fan-entity-slot[data-tier="${tier}"]`);
    const values = new Array(4).fill(null);
    slotValues.forEach(slot => {
      const idx = parseInt(slot.dataset.slot, 10);
      values[idx] = slot.dataset.current || null;
    });
    hostEl._canopyFanSlotValues[tier] = values;

    const countSel = shadowRoot.querySelector(`.canopy-fan-count-select[data-tier="${tier}"]`);
    const currentCount = countSel ? parseInt(countSel.value, 10) : values.filter(Boolean).length;
    hostEl._pendingDevices[confKey] = values.map((v, i) => (i < currentCount ? v : null));

    slotValues.forEach(slot => {
      const idx = parseInt(slot.dataset.slot, 10);
      const currentVal = slot.dataset.current || '';
      const keyDef = { key: `${tier}_fan_${idx + 1}`, label: `Fan ${idx + 1}`, domains: ['fan'] };
      const picker = _entityPickerEl(keyDef, currentVal, hostEl._hass, (val) => {
        hostEl._canopyFanSlotValues[tier][idx] = val;
        const count = countSel ? parseInt(countSel.value, 10) : 4;
        if (idx < count) hostEl._pendingDevices[confKey][idx] = val;
      });
      slot.appendChild(picker);
    });

    if (countSel) {
      countSel.addEventListener('change', () => {
        const count = parseInt(countSel.value, 10);
        shadowRoot.querySelectorAll(`.canopy-fan-slot-row[data-tier="${tier}"]`).forEach(row => {
          const idx = parseInt(row.dataset.slot, 10);
          row.hidden = idx >= count;
        });
        hostEl._pendingDevices[confKey] = hostEl._canopyFanSlotValues[tier].map(
          (v, i) => (i < count ? v : null)
        );
      });
    }
  });
}

// ── Supplemental Lighting (independent second light) ──────────────────────
// Its own clearly separate sub-section of the Primary Grow Space
// hardware-mapping form — a distinct light from Main Lighting, with its own
// entity, fixture type, and Synced/Targeted scheduling mode. Mode switching
// uses plain DOM show/hide (never a form rebuild/_render()) specifically so
// it can never reset in-progress entity-picker selections elsewhere in the
// same gear-icon form the way a rebuild would.

function _renderSupplementalLightingSection(d) {
  const mode = d.supplemental_mode === 'targeted' ? 'targeted' : 'synced';
  const targetStages = d.supplemental_target_stages || [];
  const targetableStages = Object.keys(STAGE_META).filter(s => s !== 'drying');

  return `
    <div class="sec">💡 Supplemental Lighting</div>
    <div style="font-size:.72rem;color:var(--hx-text2);margin-bottom:8px">
      A second, independent light — for UV, far-red, or other targeted spectra.
    </div>
    ${_hwPickerRow(ZONE2_SUPPLEMENTAL_HW_KEY, (d.hw_map || {}).zone2_supplemental_light || '')}
    <div class="sec">Supplemental Fixture Type</div>
    <select id="hw-supplemental-light-type-select" style="width:100%;padding:8px;border-radius:8px;
      border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)">
      ${LIGHT_TYPE_OPTIONS_JS.map(opt => `<option value="${opt}" ${
        (d.supplemental_light_type || 'led') === opt ? 'selected' : ''
      }>${LIGHT_TYPE_LABELS_JS[opt]}</option>`).join('')}
    </select>
    <div style="font-size:.7rem;color:var(--hx-text2);margin:4px 0 10px">
      If this fixture is HID/ballast class, the same hot-restrike lockout as Main Lighting applies to it.
    </div>
    <div class="sec">Supplemental Mode</div>
    <div style="display:flex;gap:6px;margin-bottom:6px">
      <button class="supplemental-mode-btn ${mode === 'synced' ? 'active' : ''}" data-mode="synced"
        style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
        background:${mode === 'synced' ? 'var(--hx-blue,#209cee)' : 'none'};color:${mode === 'synced' ? '#fff' : 'var(--hx-text)'};font-weight:600">Synced</button>
      <button class="supplemental-mode-btn ${mode === 'targeted' ? 'active' : ''}" data-mode="targeted"
        style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
        background:${mode === 'targeted' ? 'var(--hx-blue,#209cee)' : 'none'};color:${mode === 'targeted' ? '#fff' : 'var(--hx-text)'};font-weight:600">Targeted</button>
    </div>
    <div id="supplemental-mode-copy-synced" style="font-size:.7rem;color:var(--hx-text2);margin-bottom:10px" ${mode === 'synced' ? '' : 'hidden'}>
      This light turns on and off together with your main grow light, on the same schedule automatically.
    </div>
    <div id="supplemental-mode-copy-targeted" style="font-size:.7rem;color:var(--hx-text2);margin-bottom:10px" ${mode === 'targeted' ? '' : 'hidden'}>
      This light only runs during the growth stages you choose, on its own independent schedule — for example, adding UV specifically during late flower for a set number of hours per day.
    </div>
    <div id="supplemental-targeted-fields" ${mode === 'targeted' ? '' : 'hidden'}>
      <div class="sec">Target Stages</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px">
        ${targetableStages.map(s => `
          <label style="display:flex;align-items:center;gap:4px;font-size:.72rem;padding:4px 8px;
            border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);cursor:pointer">
            <input type="checkbox" class="supplemental-stage-cb" value="${s}" ${targetStages.includes(s) ? 'checked' : ''}/>
            ${STAGE_META[s].icon} ${STAGE_META[s].label}
          </label>`).join('')}
      </div>
      <div class="metric-row">
        <span class="metric-label">On At</span>
        <input type="time" id="hw-supplemental-on-time" value="${d.supplemental_on_time || '12:00'}"
          style="padding:5px;border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
      </div>
      <div class="slider-row">
        <span class="slider-lbl">Duration</span>
        <input type="range" id="hw-supplemental-duration" min="0" max="12" step="0.5" value="${d.supplemental_duration_hours ?? 2}"/>
        <span class="slider-val" id="hw-supplemental-duration-val">${fn(d.supplemental_duration_hours ?? 2, 1)}h</span>
      </div>
    </div>`;
}

function _bindSupplementalLightingSection(shadowRoot) {
  shadowRoot.querySelectorAll('.supplemental-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const chosen = btn.dataset.mode;
      shadowRoot.querySelectorAll('.supplemental-mode-btn').forEach(b => {
        const active = b.dataset.mode === chosen;
        b.classList.toggle('active', active);
        b.style.background = active ? 'var(--hx-blue,#209cee)' : 'none';
        b.style.color = active ? '#fff' : 'var(--hx-text)';
      });
      const syncedCopy = shadowRoot.querySelector('#supplemental-mode-copy-synced');
      const targetedCopy = shadowRoot.querySelector('#supplemental-mode-copy-targeted');
      const targetedFields = shadowRoot.querySelector('#supplemental-targeted-fields');
      if (syncedCopy) syncedCopy.hidden = chosen !== 'synced';
      if (targetedCopy) targetedCopy.hidden = chosen !== 'targeted';
      if (targetedFields) targetedFields.hidden = chosen !== 'targeted';
    });
  });
  const durationEl = shadowRoot.querySelector('#hw-supplemental-duration');
  const durationVal = shadowRoot.querySelector('#hw-supplemental-duration-val');
  if (durationEl) {
    durationEl.addEventListener('input', e => {
      if (durationVal) durationVal.textContent = `${fn(parseFloat(e.target.value), 1)}h`;
    });
  }
}

function _renderHwPicker(hwKeys, hwMap, hass, title, extraHtml = '', toggleValues = {}) {
  return `
    <div class="card">
      <div class="card-title">⚙ ${title} — Hardware Mapping</div>
      ${hwKeys.filter(k => !k.manualPlacement).map(k => _hwPickerRow(
        k, hwMap[k.key] || '',
        k.reverseCycleToggle
          ? { key: k.reverseCycleToggle, label: 'Reverse Cycle Unit (supplies both heat and cool)', checked: toggleValues[k.reverseCycleToggle] === true }
          : null
      )).join('')}
      ${extraHtml}
      <div style="display:flex;gap:8px;margin-top:12px">
        <button class="hw-save-btn"
          style="flex:1;padding:9px;border-radius:8px;border:none;background:var(--hx-blue,#209cee);color:#fff;cursor:pointer;font-weight:600">💾 Save</button>
        <button class="hw-cancel-btn"
          style="flex:1;padding:9px;border-radius:8px;border:1px solid var(--hx-border,#333);background:none;color:var(--hx-text);cursor:pointer">Cancel</button>
      </div>
      <div class="hw-status" style="margin-top:8px;font-size:.75rem;color:var(--hx-text2)"></div>
    </div>`;
}

function _bindHwPicker(shadowRoot, hostEl, hwKeys, extraFieldsGetter = null) {
  hostEl._pendingDevices = {};
  shadowRoot.querySelectorAll('.hw-entity-slot').forEach(slot => {
    const key = slot.dataset.key;
    const currentVal = slot.dataset.current || '';
    const keyDef = (hwKeys || []).find(k => k.key === key) || { key, label: key, domains: [] };
    const picker = _entityPickerEl(keyDef, currentVal, hostEl._hass, (val) => {
      hostEl._pendingDevices[key] = val;
    });
    slot.appendChild(picker);
  });
  const saveBtn = shadowRoot.querySelector('.hw-save-btn');
  const cancelBtn = shadowRoot.querySelector('.hw-cancel-btn');
  const statusEl = shadowRoot.querySelector('.hw-status');
  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      hostEl._isEditingHardware = false;
      hostEl._hwFormBuilt = false;
      hostEl._pendingDevices = {};
      hostEl._render();
    });
  }
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      const entryId = (hostEl._data || {}).entry_id;
      if (!hostEl._hass || !entryId) {
        if (statusEl) statusEl.textContent = 'Error: no config entry found.';
        return;
      }
      if (statusEl) statusEl.textContent = 'Saving… integration will briefly reload';
      try {
        await hostEl._hass.callWS({
          type: 'helix_cultivate/update_zone_devices',
          entry_id: entryId,
          devices: hostEl._pendingDevices,
        });
        if (extraFieldsGetter) {
          const fields = extraFieldsGetter();
          if (fields && Object.keys(fields).length) {
            await hostEl._hass.callWS({
              type: 'helix_cultivate/update_settings_fields',
              entry_id: entryId,
              fields,
            });
          }
        }
        hostEl._isEditingHardware = false;
        hostEl._hwFormBuilt = false;
        hostEl._pendingDevices = {};
        hostEl._render();
        // Tell the root panel its cached _hwMap is now stale — it re-fetches
        // get_config_summary and pushes fresh `data` (including hw_map) back
        // down, instead of this tab re-rendering from the old cached values.
        hostEl.dispatchEvent(new CustomEvent('hw-map-saved', {
          bubbles: true, composed: true,
        }));
      } catch (e) {
        if (statusEl) statusEl.textContent = 'Error saving — see console.';
        console.warn('Helix Cultivate: hardware save failed', e);
      }
    });
  }
}

// Surfaces the currently-active drying airflow overrides (2.B2) — same idea
// as the thermal-purge/VPD-assist-bias badges on the Telemetry tab, reused
// here so growers can see at a glance whether gentle-cyclic, the dedicated
// floor, or the humidity ceiling override is what's actually driving the
// exhaust right now. Shared by HelixTabDrying and HelixTabCycle's Drying
// stage card (non-dedicated-room case) so both surfaces stay consistent.
function _dryingOverrideStatusHtml(d) {
  const mode = d.drying_airflow_mode || 'constant';
  const applied = d.drying_airflow_applied_pct ?? 0;
  const floor = d.drying_exhaust_min_pct ?? 20;
  const overrideActive = d.drying_humidity_override_active === true;
  const ceiling = d.drying_humidity_ceiling_pct ?? 68;
  return `
    <div class="metric-row">
      <span class="metric-label">Gentle-Cyclic Airflow</span>
      <span class="metric-val">${fPct(applied)} (${mode === 'cyclic' ? 'cyclic' : 'constant'}, floor ${fPct(floor)})</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Humidity Ceiling Override</span>
      <span class="metric-val">${overrideActive
        ? `<span class="badge bg-red">⚠ Active — RH above ${fn(ceiling,0)}%</span>`
        : `<span class="badge bg-gray">Off</span>`}</span>
    </div>`;
}

function _gearBtnHtml() {
  return `<button class="hx-gear-btn" title="Configure Hardware"
    style="margin-left:auto;background:none;border:none;cursor:pointer;color:var(--hx-text2);font-size:1rem;line-height:1">⚙</button>`;
}

function _bindGearBtn(shadowRoot, hostEl) {
  const gearBtn = shadowRoot.querySelector('.hx-gear-btn');
  if (gearBtn) {
    gearBtn.addEventListener('click', () => {
      hostEl._isEditingHardware = true;
      hostEl._hwFormBuilt = false;
      hostEl._pendingDevices = {};
      hostEl._render();
    });
  }
}

class HelixTabGrowspace extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._isEditingHardware = false;
    this._hwFormBuilt = false;
    // Lighting & Growth Schedule drafts — survive the re-render triggered by
    // clicking growth-mode/ramp-preset (which restructures the form) until
    // an explicit Save commits them or fresh coordinator data arrives.
    this._growthModeDraft = null;
    this._rampPresetDraft = null;
    // Temporary Override section (v1.5.0 Part 4) — which context the
    // sliders are currently showing/will adjust; defaults to whichever
    // phase is actually active right now on first render (see _render()),
    // then stays as the grower left it across re-renders.
    this._overrideContext = null;
    this._overrideStatus = '';
  }

  set hass(h) { this._hass = h; }
  set data(d) { this._data = d; this._render(); }

  _svc(domain, service, data) {
    if (this._hass) this._hass.callService(domain, service, data);
  }

  // Reads every visible Lighting & Growth Schedule field straight from the
  // DOM and saves them in one explicit batch — same pattern as Zone 2
  // dimensions / stage targets. Only the currently-visible group's fields
  // (Autoflower or Photoperiod) are sent; the backend upserts individual
  // keys, so the hidden group's previously-saved values are left untouched.
  // Part 4.1/4.2 (v1.5.0): reads all three Temporary Override sliders for
  // whichever Day/Night context is currently selected and applies them in
  // one batch — a single "Apply Override" action, deliberately worded
  // differently from Plant Cycle's "Save Stage Targets" to reinforce that
  // this is not a permanent change. Each kind is sent as its own WS call
  // (the backend keeps them as independent slots), but from the user's
  // perspective this is one button.
  async _applyOverridesFromDom() {
    const q = (id) => this.shadowRoot.querySelector(id);
    const entryId = (this._data || {}).entry_id;
    const statusEl = q('#override-status');
    if (!this._hass || !entryId) {
      this._overrideStatus = '❌ Apply failed — no config entry found';
      if (statusEl) statusEl.textContent = this._overrideStatus;
      return;
    }
    const context = this._overrideContext;
    const values = [
      ['temp', parseFloat(q('#override-temp-sl').value)],
      ['vpd', parseFloat(q('#override-vpd-sl').value)],
    ];
    // v1.5.1: Light Intensity's slider is entirely absent for the Night
    // context (it has no live effect there — the grow light is forced off
    // outside its scheduled on-window regardless of ceiling), so there's
    // nothing to read from the DOM in that case.
    const lightSl = q('#override-light-sl');
    if (lightSl) values.push(['light', parseFloat(lightSl.value)]);
    this._overrideStatus = 'Applying…';
    if (statusEl) statusEl.textContent = this._overrideStatus;
    const attrKey = { temp: 'temp_c', vpd: 'vpd', light: 'light_pct' };
    try {
      for (const [kind, value] of values) {
        await this._hass.callWS({
          type: 'helix_cultivate/apply_temporary_override',
          context, kind, value,
        });
        // Optimistic patch so the 🔧 indicator appears immediately rather
        // than waiting for the next coordinator poll —
        // apply_temporary_override() already took effect server-side
        // synchronously by the time this WS call resolves. Only patch the
        // live effective value too when this context is the one actually
        // active right now — an override for the OTHER context has no
        // live effect until that context becomes active.
        this._data = { ...(this._data || {}), [`override_${context}_${attrKey[kind]}`]: value };
        if (context === ((this._data || {}).phase === 'night' ? 'night' : 'day')) {
          if (kind === 'temp') this._data.temp_setpoint = value;
          if (kind === 'vpd') this._data.vpd_target = value;
          if (kind === 'light') this._data.light_intensity_pct = value;
        }
      }
      this._overrideStatus = '✅ Applied';
    } catch (e) {
      console.error('Helix Cultivate: apply temporary override failed', e);
      this._overrideStatus = '❌ Apply failed — see console';
    }
    this._render();
  }

  async _saveLightingScheduleFromDom() {
    const q = (id) => this.shadowRoot.querySelector(id);
    const growthMode = this._growthModeDraft || (this._data || {}).growth_mode || 'photoperiod';
    const fields = { growth_mode: growthMode };

    if (growthMode === 'autoflower') {
      fields.af_light_hours = parseFloat(q('#af-hours').value);
      fields.af_lights_on_time = q('#af-on-time').value;
    } else {
      fields.pp_veg_hours = parseFloat(q('#pp-veg-hours').value);
      fields.pp_veg_lights_on_time = q('#pp-veg-on-time').value;
      fields.pp_flower_hours = parseFloat(q('#pp-flower-hours').value);
      fields.pp_flower_lights_on_time = q('#pp-flower-on-time').value;
    }

    const rampEnabledEl = q('#ramp-enabled-toggle');
    if (rampEnabledEl) fields.ramp_enabled = rampEnabledEl.checked;
    const rampPresetEl = q('#ramp-preset-select');
    if (rampPresetEl) fields.ramp_preset = rampPresetEl.value;

    // Custom ramp duration reuses the existing sunrise_ramp_min number
    // entity rather than a new settings field — live push, immediate.
    const customMinEl = q('#ramp-custom-min');
    if (customMinEl) {
      this._svc('number', 'set_value', {
        entity_id: 'number.helix_cultivate_sunrise_ramp_min',
        value: parseFloat(customMinEl.value),
      });
    }

    const entryId = (this._data || {}).entry_id;
    const statusEl = q('#lighting-save-status');
    if (!this._hass || !entryId) {
      if (statusEl) statusEl.textContent = 'Error: no config entry found.';
      return;
    }
    if (statusEl) statusEl.textContent = 'Saving…';
    try {
      await this._hass.callWS({
        type: 'helix_cultivate/update_settings_fields',
        entry_id: entryId,
        fields,
      });
      // Deliberately no _render() here — see _saveStageTargetsFromDom for
      // why: the next coordinator data push (not this WS round trip) is
      // what should refresh these fields, avoiding a visual snap-back.
      this._growthModeDraft = null;
      this._rampPresetDraft = null;
      if (statusEl) statusEl.textContent = '✅ Saved';
    } catch (e) {
      console.error('Helix Cultivate: lighting schedule save failed', e);
      if (statusEl) statusEl.textContent = '❌ Save failed — see console';
    }
  }

  _fanCard(tier, label, icon) {
    const d = this._data || {};
    const speed    = d[`${tier}_fan_speed`]    ?? 50;
    const variance = d[`${tier}_fan_variance`] ?? 20;
    const breeze   = d[`breeze_${tier}_enabled`] ?? false;
    const count    = d[`${tier}_fan_count`]    ?? 0;

    return `
      <div class="card card-sm">
        <div class="card-title">${icon} ${label}
          <span style="margin-left:auto;font-size:.7rem;color:var(--hx-text2)">${count}/4 fans</span>
        </div>
        <div class="slider-row">
          <span class="slider-lbl">Speed${breeze ? ' (base)' : ''}</span>
          <input type="range" class="fan-speed" data-tier="${tier}" min="0" max="100" step="10"
            value="${speed}"/>
          <span class="slider-val" id="spd-${tier}">${fPct(speed)}</span>
        </div>
        <div class="toggle-row" style="padding:4px 0">
          <span style="font-size:.78rem">🍃 Breeze</span>
          <label class="sw">
            <input type="checkbox" class="breeze-toggle" data-tier="${tier}" ${breeze ? 'checked' : ''}/>
            <span class="sw-track"></span>
            <span class="sw-thumb"></span>
          </label>
        </div>
        <div class="slider-row" style="${breeze ? '' : 'opacity:.4'}">
          <span class="slider-lbl">Variance ±</span>
          <input type="range" class="fan-var" data-tier="${tier}" min="0" max="50" step="5"
            value="${variance}" ${breeze ? '' : 'disabled'}/>
          <span class="slider-val" id="var-${tier}">±${fn(variance,0)}%</span>
        </div>
      </div>`;
  }

  _render() {
    const d = this._data || {};

    if (this._isEditingHardware) {
      if (this._hwFormBuilt) {
        // Form is already open — a routine coordinator data push arrived
        // mid-edit. Skip the destructive rebuild so in-progress selections
        // and any open entity-picker dropdown aren't torn down.
        return;
      }
      // Mid/lower canopy sensor and fan layers are independently toggleable —
      // sensor placement and fan placement are separate hardware decisions.
      // Upper canopy has no toggle for either; it's the mandatory primary
      // layer for both.
      const layerToggles = `
        <div class="sec">Canopy Layers</div>
        ${_hwLayerToggleRow('mid_canopy_sensor_enabled', 'Mid Canopy Sensor', d.mid_canopy_sensor_enabled !== false)}
        ${_hwLayerToggleRow('mid_canopy_fan_enabled', 'Mid Canopy Fan', d.mid_canopy_fan_enabled !== false)}
        ${_hwLayerToggleRow('lower_canopy_sensor_enabled', 'Lower Canopy Sensor', d.lower_canopy_sensor_enabled !== false)}
        ${_hwLayerToggleRow('lower_canopy_fan_enabled', 'Lower Canopy Fan', d.lower_canopy_fan_enabled !== false)}
        ${_hwLayerToggleRow('wind_sweep_enabled', '🌬 Canopy Wind Sweep', d.wind_sweep_enabled === true)}
        <div style="font-size:.7rem;color:var(--hx-text2);margin:-6px 0 4px">
          When enabled, rotates a boosted speed among the currently-enabled circulation tiers
          instead of running them all at the same static speed — mimics natural gusting wind
          to prevent microclimates and add stem-strengthening stress. Growing stages only;
          never active during Drying.
        </div>
        <div class="sec">Conditioning Room Dependency</div>
        ${_hwLayerToggleRow('zone2_depends_on_conditioning', 'Depends on Conditioning Room', d.zone2_depends_on_conditioning !== false)}
        <div style="font-size:.7rem;color:var(--hx-text2);margin:-6px 0 4px">
          On (the safe default) if this space relies on the Conditioning Room for its own
          baseline climate rather than having its own independent heater/AirCon/dehumidifier —
          gates whether Conditioning Room is allowed to run Deep Calibration (Environmental
          Learning) while this space is occupied. Always an explicit choice — never
          auto-decided silently, since guessing wrong here risks a ruined harvest.
        </div>
        <div class="sec">Exhaust Fan</div>
        ${_hwPickerRow(ZONE2_HW_KEYS.find(k => k.key === 'exhaust_fan'), (d.hw_map || {}).exhaust_fan || '')}
        ${_renderCanopyFanMappingSection(d)}
        <div class="sec">Grow Light Fixture Type</div>
        <select id="hw-light-type-select" style="width:100%;padding:8px;border-radius:8px;
          border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)">
          ${LIGHT_TYPE_OPTIONS_JS.map(opt => `<option value="${opt}" ${
            (d.zone2_light_type || 'led') === opt ? 'selected' : ''
          }>${LIGHT_TYPE_LABELS_JS[opt]}</option>`).join('')}
        </select>
        <div style="font-size:.7rem;color:var(--hx-text2);margin-top:4px">
          Drives the default leaf-temperature offset and HID/ballast hot-restrike lockout.
        </div>
        <div class="sec">High-Temperature Light Dimming</div>
        <div class="slider-row">
          <span class="slider-lbl">Soft Dim Threshold</span>
          <input type="range" id="hw-light-high-temp-dim-slider" min="20" max="31" step="0.5"
            value="${d.light_high_temp_dim_c ?? 29.0}"/>
          <span class="slider-val" id="hw-light-high-temp-dim-val">${fn(d.light_high_temp_dim_c ?? 29.0, 1)}°C</span>
        </div>
        <div style="font-size:.7rem;color:var(--hx-text2);margin-top:4px">
          At this canopy temperature, light intensity is throttled to 50% — a soft step
          strictly below the hard 32°C thermal-runaway cutoff (which forces the light fully off).
        </div>
        ${_hwPickerRow(ZONE2_HW_KEYS.find(k => k.key === 'zone2_grow_light'), (d.hw_map || {}).zone2_grow_light || '')}
        ${_hwPickerRow(ZONE2_HW_KEYS.find(k => k.key === 'dli_sensor'), (d.hw_map || {}).dli_sensor || '')}
        ${_renderSupplementalLightingSection(d)}`;

      this.shadowRoot.innerHTML = `<style>${BASE_CSS}:host{display:block;}</style>`
        + _renderHwPicker(
            ZONE2_HW_KEYS, d.hw_map || {}, this._hass,
            d.zone2_name || 'Primary Grow Space', layerToggles, d
          );
      _bindHwPicker(this.shadowRoot, this, [...ZONE2_HW_KEYS, ZONE2_SUPPLEMENTAL_HW_KEY], () => {
        const fields = {};
        this.shadowRoot.querySelectorAll('.hw-layer-toggle').forEach(el => {
          fields[el.dataset.layer] = el.checked;
        });
        const supplementalTypeSel = this.shadowRoot.querySelector('#hw-supplemental-light-type-select');
        if (supplementalTypeSel) fields.supplemental_light_type = supplementalTypeSel.value;
        const modeEl = this.shadowRoot.querySelector('.supplemental-mode-btn.active');
        fields.supplemental_mode = modeEl ? modeEl.dataset.mode : 'synced';
        const stageChecks = this.shadowRoot.querySelectorAll('.supplemental-stage-cb:checked');
        fields.supplemental_target_stages = Array.from(stageChecks).map(cb => cb.value);
        const onTimeEl = this.shadowRoot.querySelector('#hw-supplemental-on-time');
        if (onTimeEl) fields.supplemental_on_time = onTimeEl.value;
        const durationEl = this.shadowRoot.querySelector('#hw-supplemental-duration');
        if (durationEl) fields.supplemental_duration_hours = parseFloat(durationEl.value);
        const dimSl = this.shadowRoot.querySelector('#hw-light-high-temp-dim-slider');
        if (dimSl) fields.light_high_temp_dim_c = parseFloat(dimSl.value);
        return fields;
      });
      // Runs after _bindHwPicker (which resets _pendingDevices = {}) so the
      // canopy fan lists it populates directly into _pendingDevices survive.
      _bindCanopyFanMappingSection(this.shadowRoot, this);
      // Light type is a live select entity — persists immediately on
      // change, independent of the hardware-mapping Save button above.
      const lightTypeSel = this.shadowRoot.querySelector('#hw-light-type-select');
      if (lightTypeSel) {
        lightTypeSel.addEventListener('change', e => {
          this._svc('select', 'select_option', {
            entity_id: 'select.helix_cultivate_light_type', option: e.target.value,
          });
        });
      }
      const dimSl = this.shadowRoot.querySelector('#hw-light-high-temp-dim-slider');
      const dimVal = this.shadowRoot.querySelector('#hw-light-high-temp-dim-val');
      if (dimSl) {
        dimSl.addEventListener('input', e => {
          if (dimVal) dimVal.textContent = `${fn(parseFloat(e.target.value), 1)}°C`;
        });
      }
      _bindSupplementalLightingSection(this.shadowRoot);
      this._hwFormBuilt = true;
      return;
    }

    const vpd     = d.leaf_vpd     ?? null;
    const vpdT    = d.vpd_target   ?? 1.0;
    const tempSP  = d.temp_setpoint ?? 24;
    const lightP  = d.light_intensity_pct ?? 100;
    const exhaust = d.exhaust_pct ?? null;

    // Temporary Override system (v1.5.0 Part 4) — defaults the toggle to
    // whichever phase is actually active right now, on first render only;
    // afterward it stays wherever the grower left it.
    if (this._overrideContext === null) this._overrideContext = d.phase === 'night' ? 'night' : 'day';
    const overrideCtx = this._overrideContext;
    const overrideTempActive = overrideCtx === 'day' ? d.override_day_temp_c : d.override_night_temp_c;
    const overrideVpdActive = overrideCtx === 'day' ? d.override_day_vpd : d.override_night_vpd;
    const overrideLightActive = overrideCtx === 'day' ? d.override_day_light_pct : d.override_night_light_pct;

    // Appliance state chips
    const applianceRow = `
      <div class="chip-row" style="margin-bottom:10px">
        ${overrideChip('Heater',   null, d.zone2_heater_on,  this._hass, true)}
        ${overrideChip('AC',       null, d.zone2_ac_on,      this._hass, true)}
        ${overrideChip('Humidifier', null, d.zone2_humid_on,  this._hass, true)}
        ${overrideChip('Dehumidifier', null, d.zone2_dehumid_on, this._hass, true)}
        ${overrideChip('Exhaust',  null, (exhaust ?? 0) > 10, this._hass, true)}
      </div>`;

    const midSensorOn = d.mid_canopy_sensor_enabled !== false;
    const lowerSensorOn = d.lower_canopy_sensor_enabled !== false;
    const midFanOn = d.mid_canopy_fan_enabled !== false;
    const lowerFanOn = d.lower_canopy_fan_enabled !== false;

    // Part 2: a disabled Mid/Lower sensor tier renders an actual placeholder
    // cell rather than an empty string — an empty string collapses in the
    // CSS grid, so the next real cell auto-flows into the freed column and
    // Lower ends up sitting where Mid should be. A placeholder keeps all
    // three columns fixed (Upper/Mid/Lower) regardless of which tiers are
    // enabled.
    const tempCells = [
      `<div class="stat-cell"><div class="val" style="color:#ef4444">${fT(d.upper_temp_c)}</div><div class="lbl">Upper °C</div></div>`,
      midSensorOn ? `<div class="stat-cell"><div class="val" style="color:#ef4444">${fT(d.mid_temp_c)}</div><div class="lbl">Mid °C</div></div>` : `<div class="stat-cell disabled"><div class="val">—</div><div class="lbl">Mid °C</div></div>`,
      lowerSensorOn ? `<div class="stat-cell"><div class="val" style="color:#ef4444">${fT(d.lower_temp_c)}</div><div class="lbl">Lower °C</div></div>` : `<div class="stat-cell disabled"><div class="val">—</div><div class="lbl">Lower °C</div></div>`,
    ].join('');
    const rhCells = [
      `<div class="stat-cell"><div class="val" style="color:#209cee">${fRH(d.upper_rh_pct)}</div><div class="lbl">Upper RH</div></div>`,
      midSensorOn ? `<div class="stat-cell"><div class="val" style="color:#209cee">${fRH(d.mid_rh_pct)}</div><div class="lbl">Mid RH</div></div>` : `<div class="stat-cell disabled"><div class="val">—</div><div class="lbl">Mid RH</div></div>`,
      lowerSensorOn ? `<div class="stat-cell"><div class="val" style="color:#209cee">${fRH(d.lower_rh_pct)}</div><div class="lbl">Lower RH</div></div>` : `<div class="stat-cell disabled"><div class="val">—</div><div class="lbl">Lower RH</div></div>`,
    ].join('');

    const uniformityHtml = (d.canopy_uniformity_insight)
      ? `<div class="metric-row" style="margin-top:4px">
           <span class="metric-label">⚠ Canopy Uniformity</span>
           <span class="metric-val" style="color:var(--hx-amber);font-size:.78rem;text-align:right">${d.canopy_uniformity_insight}</span>
         </div>` : '';

    // Part 3.3: a tier with 0 mapped fans has nothing to control, so its
    // card is fully absent from the matrix — distinct from Part 2's
    // sensor-cell fix, which keeps an empty PLACEHOLDER for temp/RH
    // specifically to preserve fixed grid columns. There's no equivalent
    // fixed-position requirement for fan control cards.
    const fanCards = [
      (d.upper_fan_count ?? 0) > 0 ? this._fanCard('upper','Upper Canopy','⬆') : '',
      midFanOn && (d.mid_fan_count ?? 0) > 0 ? this._fanCard('mid','Mid Canopy','⟺') : '',
      lowerFanOn && (d.lower_fan_count ?? 0) > 0 ? this._fanCard('lower','Lower Canopy','⬇') : '',
    ].join('');

    // ── Lighting & Growth Schedule (Phase 1.5) ──────────────────────────────
    const growLightId = (d.hw_map || {}).zone2_grow_light || null;
    const isDimmable = !!growLightId && growLightId.startsWith('light.');
    const growthMode = (this._growthModeDraft || d.growth_mode) === 'autoflower' ? 'autoflower' : 'photoperiod';
    const rampPresetActive = this._rampPresetDraft || d.ramp_preset || 'standard';

    // B6: live on/off status reflects the entity's ACTUAL state, not the
    // schedule's intended state — stays honest if something's gone wrong.
    let lightStatusHtml = '<span class="metric-val" style="color:var(--hx-text2)">Not mapped</span>';
    if (growLightId && this._hass && this._hass.states[growLightId]) {
      const lightIsOn = this._hass.states[growLightId].state === 'on';
      lightStatusHtml = lightIsOn
        ? '<span class="metric-val" style="color:var(--hx-amber)">🌞 Lights On</span>'
        : '<span class="metric-val" style="color:var(--hx-text2)">🌙 Dark Period</span>';
    }

    const scheduleFieldsHtml = growthMode === 'autoflower' ? `
      <div class="sec">Constant Schedule (applies across the entire grow)</div>
      <div class="slider-row">
        <span class="slider-lbl">Light Hours</span>
        <input type="range" id="af-hours" min="0" max="24" step="0.5" value="${fn(d.af_light_hours, 1)}"/>
        <span class="slider-val" id="af-hours-val">${fn(d.af_light_hours, 1)}h</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">Lights On At</span>
        <input type="time" id="af-on-time" value="${d.af_lights_on_time}"
          style="padding:5px;border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
      </div>
      <div class="metric-row">
        <span class="metric-label">Derived Off Time</span>
        <span class="metric-val" id="af-off-time-display">${_deriveOffTime(d.af_lights_on_time, d.af_light_hours)}</span>
      </div>
    ` : `
      <div class="sec">Vegetative Schedule — Germination → Late Veg</div>
      <div class="slider-row">
        <span class="slider-lbl">Light Hours</span>
        <input type="range" id="pp-veg-hours" min="0" max="24" step="0.5" value="${fn(d.pp_veg_hours, 1)}"/>
        <span class="slider-val" id="pp-veg-hours-val">${fn(d.pp_veg_hours, 1)}h</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">Lights On At</span>
        <input type="time" id="pp-veg-on-time" value="${d.pp_veg_lights_on_time}"
          style="padding:5px;border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
      </div>
      <div class="metric-row">
        <span class="metric-label">Derived Off Time</span>
        <span class="metric-val" id="pp-veg-off-time-display">${_deriveOffTime(d.pp_veg_lights_on_time, d.pp_veg_hours)}</span>
      </div>
      <div class="sec">Flowering Schedule — Stretch → Ripening</div>
      <div class="slider-row">
        <span class="slider-lbl">Light Hours</span>
        <input type="range" id="pp-flower-hours" min="0" max="24" step="0.5" value="${fn(d.pp_flower_hours, 1)}"/>
        <span class="slider-val" id="pp-flower-hours-val">${fn(d.pp_flower_hours, 1)}h</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">Lights On At</span>
        <input type="time" id="pp-flower-on-time" value="${d.pp_flower_lights_on_time}"
          style="padding:5px;border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
      </div>
      <div class="metric-row">
        <span class="metric-label">Derived Off Time</span>
        <span class="metric-val" id="pp-flower-off-time-display">${_deriveOffTime(d.pp_flower_lights_on_time, d.pp_flower_hours)}</span>
      </div>
    `;

    const rampSectionHtml = isDimmable ? `
      <select id="ramp-preset-select" style="width:100%;padding:7px;border-radius:8px;margin-top:6px;
        border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)" ${d.ramp_enabled ? '' : 'disabled'}>
        ${Object.keys(RAMP_PRESET_LABELS_JS).map(p => `<option value="${p}" ${rampPresetActive === p ? 'selected' : ''}>${RAMP_PRESET_LABELS_JS[p]}</option>`).join('')}
      </select>
      ${rampPresetActive === 'custom' ? `
        <div class="slider-row" style="margin-top:6px">
          <span class="slider-lbl">Custom Minutes</span>
          <input type="range" id="ramp-custom-min" min="1" max="60" step="1" value="${d.sunrise_ramp_min ?? 20}" ${d.ramp_enabled ? '' : 'disabled'}/>
          <span class="slider-val" id="ramp-custom-min-val">${d.sunrise_ramp_min ?? 20} min</span>
        </div>` : ''}
    ` : `<div style="font-size:.72rem;color:var(--hx-text2);margin-top:4px">
        Switch-domain lights can't dim — ramp is automatically disabled.
      </div>`;

    const dliToday = d.dli_today ?? 0;
    const targetDli = d.target_dli_mol ?? 0;
    const dliPct = targetDli > 0 ? Math.round((dliToday / targetDli) * 100) : null;
    const dliIndicatorHtml = targetDli > 0 ? `
      <div class="metric-row" style="margin-bottom:8px">
        <span class="metric-label">Today's DLI</span>
        <span class="metric-val">${fn(dliToday, 1)} / Target: ${fn(targetDli, 0)} mol (${dliPct}%)</span>
      </div>` : '';

    // Part 1.2 (v1.5.0): Growth Mode is locked read-only the moment
    // Primary Grow Space is occupied — reusing the same CONF_ZONE2_OCCUPIED
    // flag the Environmental Learning gating work established, since it
    // already correctly answers "is a plant currently in this space"
    // across both topologies. Applies here identically to the Plant Cycle
    // tab's own copy of this same toggle — one config value, one lock rule.
    const zone2OccupiedGrowspace = d.zone2_occupied === true;
    const growthModeLockNoticeHtml = zone2OccupiedGrowspace ? `
      <div style="font-size:.7rem;color:var(--hx-text2);margin:-4px 0 10px">
        🔒 Locked while a cycle occupies Primary Grow Space — changing Growth
        Mode mid-cycle would abruptly change the active lighting schedule.
      </div>` : '';
    const lightingCardHtml = `
      <div class="card">
        <div class="card-title">💡 Lighting &amp; Growth Schedule</div>
        <div class="metric-row" style="margin-bottom:8px">
          <span class="metric-label">Grow Light</span>
          ${lightStatusHtml}
        </div>
        ${dliIndicatorHtml}
        <div class="hx-period-toggle" style="display:flex;gap:6px;margin-bottom:12px">
          <button class="growth-mode-btn ${growthMode === 'autoflower' ? 'active' : ''}" data-mode="autoflower"
            ${zone2OccupiedGrowspace ? 'disabled' : ''}
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);
            cursor:${zone2OccupiedGrowspace ? 'not-allowed' : 'pointer'};opacity:${zone2OccupiedGrowspace ? '0.6' : '1'};
            background:${growthMode === 'autoflower' ? 'var(--hx-blue,#209cee)' : 'none'};color:${growthMode === 'autoflower' ? '#fff' : 'var(--hx-text)'};font-weight:600">🌻 Autoflower</button>
          <button class="growth-mode-btn ${growthMode === 'photoperiod' ? 'active' : ''}" data-mode="photoperiod"
            ${zone2OccupiedGrowspace ? 'disabled' : ''}
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);
            cursor:${zone2OccupiedGrowspace ? 'not-allowed' : 'pointer'};opacity:${zone2OccupiedGrowspace ? '0.6' : '1'};
            background:${growthMode === 'photoperiod' ? 'var(--hx-blue,#209cee)' : 'none'};color:${growthMode === 'photoperiod' ? '#fff' : 'var(--hx-text)'};font-weight:600">🌗 Photoperiod</button>
        </div>
        ${growthModeLockNoticeHtml}
        ${scheduleFieldsHtml}
        <div class="sec">Sunrise / Sunset Dimming Ramp</div>
        <div class="toggle-row">
          <span class="toggle-lbl">Enable Ramp</span>
          <label class="sw">
            <input type="checkbox" id="ramp-enabled-toggle" ${d.ramp_enabled ? 'checked' : ''} ${isDimmable ? '' : 'disabled'}/>
            <span class="sw-track"></span>
            <span class="sw-thumb"></span>
          </label>
        </div>
        ${rampSectionHtml}
        <div style="display:flex;align-items:center;gap:10px;margin-top:12px">
          <button id="save-lighting-btn" style="padding:9px 16px;border-radius:8px;border:none;
            background:var(--hx-blue,#209cee);color:#fff;font-weight:600;cursor:pointer">💾 Save Lighting Schedule</button>
          <span id="lighting-save-status" style="font-size:.75rem;color:var(--hx-text2)"></span>
        </div>
      </div>`;

    this.shadowRoot.innerHTML = `
      <style>${BASE_CSS}:host{display:block;}</style>
      <!-- Part 6 (v1.5.0): explanatory copy, verbatim -->
      <div style="font-size:.78rem;color:var(--hx-text2);margin-bottom:10px;line-height:1.5">
        This is where you monitor and fine-tune your grow space in real time.
      </div>
      <!-- Live readings -->
      <div class="card">
        <div class="card-title" style="display:flex;align-items:center">🌱 ${d.zone2_name || 'Primary Grow Space'} — Live ${_gearBtnHtml()}</div>
        ${applianceRow}
        <div class="g3">
          ${tempCells}
          ${rhCells}
        </div>
        ${uniformityHtml}
        <hr/>
        <div class="metric-row">
          <span class="metric-label">Leaf VPD</span>
          <span class="metric-val" style="color:${vpdColour(vpd,vpdT)}">${fVPD(vpd)}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Exhaust</span>
          <span class="metric-val" style="color:var(--hx-blue)">${fPct(exhaust)}</span>
        </div>
      </div>
      <!-- Setpoints -->
      <div class="card">
        <div class="card-title">🎯 Setpoints &amp; Controls</div>
        <div style="font-size:.7rem;color:var(--hx-text2);margin-bottom:8px">
          Live effective values right now — permanent stage targets are edited on the
          Plant Cycle tab; temporary nudges are below.
        </div>
        <div class="metric-row">
          <span class="metric-label">Temp Setpoint</span>
          <span class="metric-val">${fT(tempSP)} ${overrideTempActive != null ? OVERRIDE_BADGE : ''}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">VPD Target</span>
          <span class="metric-val">${fVPD(vpdT)} ${overrideVpdActive != null ? OVERRIDE_BADGE : ''}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Light Intensity</span>
          <span class="metric-val">${fPct(lightP)} ${overrideLightActive != null ? OVERRIDE_BADGE : ''}</span>
        </div>
      </div>
      <!-- Temporary Override (v1.5.0 Part 4) -->
      <div class="card">
        <div class="card-title">🔧 Temporary Override</div>
        <div style="font-size:.72rem;color:var(--hx-text2);margin-bottom:10px;line-height:1.5">
          🔧 Temporary Override — these sliders let you nudge today's temperature, VPD, or light
          intensity without changing your saved stage settings. An override stays active until
          this stage ends, then automatically resets to your saved default. To make a permanent
          change instead, edit it on the Plant Cycle tab.
        </div>
        <div class="hx-period-toggle" style="display:flex;gap:6px;margin-bottom:12px">
          <button class="override-context-btn ${overrideCtx === 'day' ? 'active' : ''}" data-context="day"
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
            background:${overrideCtx === 'day' ? 'var(--hx-blue,#209cee)' : 'none'};color:${overrideCtx === 'day' ? '#fff' : 'var(--hx-text)'};font-weight:600">☀️ Day</button>
          <button class="override-context-btn ${overrideCtx === 'night' ? 'active' : ''}" data-context="night"
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
            background:${overrideCtx === 'night' ? 'var(--hx-blue,#209cee)' : 'none'};color:${overrideCtx === 'night' ? '#fff' : 'var(--hx-text)'};font-weight:600">🌙 Night</button>
        </div>
        ${_renderOverrideSlidersHtml(overrideCtx, tempSP, vpdT, lightP, overrideTempActive, overrideVpdActive, overrideLightActive)}
        <div style="display:flex;align-items:center;gap:10px;margin-top:8px">
          <button id="apply-override-btn" style="padding:9px 16px;border-radius:8px;border:none;
            background:var(--hx-amber,#e6a817);color:#111;font-weight:700;cursor:pointer">🔧 Apply Override</button>
          <span id="override-status" style="font-size:.75rem;color:var(--hx-text2)">${this._overrideStatus}</span>
        </div>
      </div>
      ${lightingCardHtml}
      <!-- Fan matrix -->
      <div class="sec">🌀 Circulation Fan Matrix</div>
      <div class="g3">
        ${fanCards}
      </div>`;

    // Day/Night context toggle for the Temporary Override section
    this.shadowRoot.querySelectorAll('.override-context-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._overrideContext = btn.dataset.context;
        this._render();
      });
    });

    // Live slider-value labels (no auto-apply — explicit button below)
    const overrideSliderBindings = [
      ['#override-temp-sl', '#override-temp-val', fT],
      ['#override-vpd-sl', '#override-vpd-val', fVPD],
      ['#override-light-sl', '#override-light-val', fPct],
    ];
    for (const [slId, valId, fmt] of overrideSliderBindings) {
      const sl = this.shadowRoot.querySelector(slId);
      const vl = this.shadowRoot.querySelector(valId);
      if (!sl) continue;
      sl.addEventListener('input', e => { if (vl) vl.textContent = fmt(parseFloat(e.target.value)); });
    }
    const applyOverrideBtn = this.shadowRoot.querySelector('#apply-override-btn');
    if (applyOverrideBtn) {
      applyOverrideBtn.addEventListener('click', () => this._applyOverridesFromDom());
    }

    // Fan speed sliders
    this.shadowRoot.querySelectorAll('.fan-speed').forEach(sl => {
      const tier = sl.dataset.tier;
      const vEl = this.shadowRoot.querySelector(`#spd-${tier}`);
      sl.addEventListener('input', e => { if (vEl) vEl.textContent = fPct(parseFloat(e.target.value)); });
      sl.addEventListener('change', e => this._svc('number', 'set_value', {
        entity_id: `number.helix_cultivate_${tier}_fan_speed`, value: parseFloat(e.target.value)
      }));
    });

    // Fan variance sliders
    this.shadowRoot.querySelectorAll('.fan-var').forEach(sl => {
      const tier = sl.dataset.tier;
      const vEl = this.shadowRoot.querySelector(`#var-${tier}`);
      sl.addEventListener('input', e => { if (vEl) vEl.textContent = `±${fn(parseFloat(e.target.value),0)}%`; });
      sl.addEventListener('change', e => this._svc('number', 'set_value', {
        entity_id: `number.helix_cultivate_${tier}_fan_variance`, value: parseFloat(e.target.value)
      }));
    });

    // Breeze toggles
    this.shadowRoot.querySelectorAll('.breeze-toggle').forEach(cb => {
      const tier = cb.dataset.tier;
      cb.addEventListener('change', e => {
        this._svc('switch', e.target.checked ? 'turn_on' : 'turn_off', {
          entity_id: `switch.helix_cultivate_breeze_${tier}`
        });
      });
    });

    // ── Lighting & Growth Schedule bindings ─────────────────────────────────

    // Growth mode toggle — structurally mutually exclusive (two buttons,
    // one active class) rather than independent checkboxes, so "both" or
    // "neither" selected is impossible. Re-renders to swap the field group;
    // tracked as a draft so the choice survives that re-render until Saved.
    this.shadowRoot.querySelectorAll('.growth-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._growthModeDraft = btn.dataset.mode;
        this._render();
      });
    });

    // Live hour-slider labels + derived off-time previews
    const hourFields = [
      ['#af-hours', '#af-hours-val', '#af-on-time', '#af-off-time-display'],
      ['#pp-veg-hours', '#pp-veg-hours-val', '#pp-veg-on-time', '#pp-veg-off-time-display'],
      ['#pp-flower-hours', '#pp-flower-hours-val', '#pp-flower-on-time', '#pp-flower-off-time-display'],
    ];
    for (const [hoursId, valId, onTimeId, offDisplayId] of hourFields) {
      const hoursEl = this.shadowRoot.querySelector(hoursId);
      const valEl = this.shadowRoot.querySelector(valId);
      const onTimeEl = this.shadowRoot.querySelector(onTimeId);
      const offDisplayEl = this.shadowRoot.querySelector(offDisplayId);
      if (!hoursEl) continue;
      const refreshOff = () => {
        if (offDisplayEl && onTimeEl) {
          offDisplayEl.textContent = _deriveOffTime(onTimeEl.value, parseFloat(hoursEl.value));
        }
      };
      hoursEl.addEventListener('input', e => {
        if (valEl) valEl.textContent = `${fn(parseFloat(e.target.value), 1)}h`;
        refreshOff();
      });
      if (onTimeEl) onTimeEl.addEventListener('input', refreshOff);
    }

    // Ramp enabled toggle — simple enable/disable of sibling controls, no
    // re-render needed (nothing restructures, just becomes usable/greyed).
    const rampEnabledToggle = this.shadowRoot.querySelector('#ramp-enabled-toggle');
    if (rampEnabledToggle) {
      rampEnabledToggle.addEventListener('change', e => {
        const enabled = e.target.checked;
        const presetSel = this.shadowRoot.querySelector('#ramp-preset-select');
        if (presetSel) presetSel.disabled = !enabled;
        const customMin = this.shadowRoot.querySelector('#ramp-custom-min');
        if (customMin) customMin.disabled = !enabled;
      });
    }

    // Ramp preset — "custom" reveals the custom-minutes slider, a structural
    // change, so re-render (tracked as a draft, same reasoning as growth mode).
    const rampPresetSelect = this.shadowRoot.querySelector('#ramp-preset-select');
    if (rampPresetSelect) {
      rampPresetSelect.addEventListener('change', e => {
        this._rampPresetDraft = e.target.value;
        this._render();
      });
    }
    const rampCustomMin = this.shadowRoot.querySelector('#ramp-custom-min');
    const rampCustomMinVal = this.shadowRoot.querySelector('#ramp-custom-min-val');
    if (rampCustomMin) {
      rampCustomMin.addEventListener('input', e => {
        if (rampCustomMinVal) rampCustomMinVal.textContent = `${e.target.value} min`;
      });
    }

    // Explicit Save — reads every visible lighting field straight from the
    // DOM in one batch, exactly like Zone 2 dimensions / stage targets.
    const saveLightingBtn = this.shadowRoot.querySelector('#save-lighting-btn');
    if (saveLightingBtn) {
      saveLightingBtn.addEventListener('click', () => this._saveLightingScheduleFromDom());
    }

    _bindGearBtn(this.shadowRoot, this);
  }
  connectedCallback() { this._render(); }
}
customElements.define('helix-tab-growspace', HelixTabGrowspace);

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Conditioning Room  <helix-tab-conditioning>
// ─────────────────────────────────────────────────────────────────────────────

class HelixTabConditioning extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); this._isEditingHardware = false; this._hwFormBuilt = false; }

  set hass(h) { this._hass = h; }
  set data(d) { this._data = d; this._render(); }

  _render() {
    const d = this._data || {};

    if (this._isEditingHardware) {
      if (this._hwFormBuilt) {
        // Form is already open — a routine coordinator data push arrived
        // mid-edit. Skip the destructive rebuild so in-progress selections
        // and any open entity-picker dropdown aren't torn down.
        return;
      }
      const preheatSectionHtml = `
        <div class="sec">Predictive Pre-Heating</div>
        <div class="slider-row">
          <span class="slider-lbl">Lead Time</span>
          <input type="range" id="hw-preheat-lead-slider" min="0" max="60" step="5"
            value="${d.preheat_lead_min ?? 15}"/>
          <span class="slider-val" id="hw-preheat-lead-val">${d.preheat_lead_min ?? 15} min</span>
        </div>
        <div style="font-size:.7rem;color:var(--hx-text2);margin-top:4px">
          This many minutes before the scheduled lights-off transition, the lung-room heater
          is proactively nudged on ahead of the temperature drop that follows — rather than
          reacting after it's already started falling. Set to 0 to disable.
        </div>`;

      this.shadowRoot.innerHTML = `<style>${BASE_CSS}:host{display:block;}</style>`
        + _renderHwPicker(
            ZONE1_HW_KEYS, d.hw_map || {}, this._hass,
            d.zone1_name || 'Conditioning Room', preheatSectionHtml, d
          );
      _bindHwPicker(this.shadowRoot, this, ZONE1_HW_KEYS, () => {
        const fields = {};
        const preheatSl = this.shadowRoot.querySelector('#hw-preheat-lead-slider');
        if (preheatSl) fields.preheat_lead_min = parseFloat(preheatSl.value);
        return fields;
      });
      const preheatSl = this.shadowRoot.querySelector('#hw-preheat-lead-slider');
      const preheatVal = this.shadowRoot.querySelector('#hw-preheat-lead-val');
      if (preheatSl) {
        preheatSl.addEventListener('input', e => {
          if (preheatVal) preheatVal.textContent = `${e.target.value} min`;
        });
      }
      this._hwFormBuilt = true;
      return;
    }

    const temp   = d.lung_temp_c  ?? null;
    const rh     = d.lung_rh_pct  ?? null;
    const enthal = d.lung_enthalpy ?? null;
    const vpdT   = d.vpd_target   ?? 1.0;
    const tempSP = d.temp_setpoint ?? 24;

    this.shadowRoot.innerHTML = `
      <style>${BASE_CSS}:host{display:block;}</style>
      <div class="card">
        <div class="card-title" style="display:flex;align-items:center">🌬 ${d.zone1_name || 'Conditioning Room'} — Live ${_gearBtnHtml()}</div>
        <div class="chip-row" style="margin-bottom:10px">
          ${overrideChip('Heater',     null, d.zone1_heater_on,  this._hass, true)}
          ${overrideChip('AC',         null, d.zone1_ac_on,      this._hass, true)}
          ${overrideChip('Humidifier', null, d.zone1_humid_on,   this._hass, true)}
          ${overrideChip('Dehumidifier', null, d.zone1_dehumid_on, this._hass, true)}
          ${overrideChip('Backup Heat', null, d.zone1_backup_heater_on, this._hass, !!d.zone1_backup_heater_on)}
        </div>
        <div class="g2">
          <div class="stat-cell"><div class="val" style="color:#ef4444">${fT(temp)}</div><div class="lbl">Temperature</div></div>
          <div class="stat-cell"><div class="val" style="color:#209cee">${fRH(rh)}</div><div class="lbl">Humidity</div></div>
        </div>
        <hr/>
        <div class="metric-row">
          <span class="metric-label">Enthalpy</span>
          <span class="metric-val">${enthal != null ? fn(enthal,1) + ' kJ/kg' : '—'}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">RC Mode</span>
          <span class="metric-val">${d.zone1_reverse_cycle_mode || '—'}</span>
        </div>
      </div>
      <div class="card">
        <div class="card-title">🎯 Setpoints</div>
        <div class="slider-row">
          <span class="slider-lbl">Temp Setpoint</span>
          <input type="range" id="z1-temp" min="15" max="30" step="0.5" value="${tempSP}"/>
          <span class="slider-val" id="z1-temp-val">${fT(tempSP)}</span>
        </div>
      </div>`;

    const sl = this.shadowRoot.querySelector('#z1-temp');
    const vl = this.shadowRoot.querySelector('#z1-temp-val');
    if (sl) {
      sl.addEventListener('input', e => { if (vl) vl.textContent = fT(parseFloat(e.target.value)); });
      sl.addEventListener('change', e => {
        if (this._hass) this._hass.callService('number', 'set_value', {
          entity_id: 'number.helix_cultivate_temp_setpoint', value: parseFloat(e.target.value)
        });
      });
    }

    _bindGearBtn(this.shadowRoot, this);
  }
  connectedCallback() { this._render(); }
}
customElements.define('helix-tab-conditioning', HelixTabConditioning);

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Drying Environment  <helix-tab-drying>
// ─────────────────────────────────────────────────────────────────────────────

class HelixTabDrying extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._isEditingHardware = false;
    this._hwFormBuilt = false;
    this._editingPeriod = 'day';
    this._stageDraft = {};
  }

  set hass(h) { this._hass = h; }
  set data(d) { this._data = d; this._render(); }

  async _toggleDryingLock(unlocked) {
    const entryId = (this._data || {}).entry_id;
    if (!this._hass || !entryId) return;
    try {
      await this._hass.callWS({
        type: 'helix_cultivate/toggle_drying_lock',
        entry_id: entryId,
        unlocked,
      });
      this._data = { ...this._data, is_drying_unlocked: unlocked };
      this._render();
    } catch (e) {
      console.error('Helix Cultivate: drying lock toggle failed', e);
    }
  }

  _draftValue(key) {
    if (this._stageDraft[key] !== undefined) return this._stageDraft[key];
    const persisted = (this._data || {})['stage_targets_drying'];
    if (persisted && persisted[key] !== undefined) return persisted[key];
    return STAGE_DAYNIGHT_DEFAULTS_JS.drying[key];
  }

  async _saveDryingTargets() {
    const draft = this._stageDraft;
    if (!Object.keys(draft).length) return;
    const entryId = (this._data || {}).entry_id;
    if (!this._hass || !entryId) return;
    try {
      await this._hass.callWS({
        type: 'helix_cultivate/update_stage_targets',
        entry_id: entryId,
        stage: 'drying',
        targets: draft,
      });
    } catch (e) {
      console.error('Helix Cultivate: drying stage target save failed', e);
    }
  }

  _render() {
    const d = this._data || {};

    if (this._isEditingHardware) {
      if (this._hwFormBuilt) {
        // Form is already open — a routine coordinator data push arrived
        // mid-edit. Skip the destructive rebuild so in-progress selections
        // and any open entity-picker dropdown aren't torn down.
        return;
      }
      const dryingDependencyHtml = `
        <div class="sec">Conditioning Room Dependency</div>
        ${_hwLayerToggleRow('drying_depends_on_conditioning', 'Depends on Conditioning Room', d.drying_depends_on_conditioning !== false)}
        <div style="font-size:.7rem;color:var(--hx-text2);margin:-6px 0 4px">
          On (the safe default) if this room relies on the Conditioning Room for its own
          baseline climate rather than having its own independent heater/AirCon/dehumidifier —
          gates whether Conditioning Room is allowed to run Deep Calibration while curing
          material occupies this room.
        </div>`;
      this.shadowRoot.innerHTML = `<style>${BASE_CSS}:host{display:block;}</style>`
        + _renderHwPicker(DRYING_HW_KEYS, d.hw_map || {}, this._hass, d.drying_zone_name || 'Drying Room', dryingDependencyHtml, d);
      _bindHwPicker(this.shadowRoot, this, DRYING_HW_KEYS, () => {
        const fields = {};
        this.shadowRoot.querySelectorAll('.hw-layer-toggle').forEach(el => {
          fields[el.dataset.layer] = el.checked;
        });
        return fields;
      });
      this._hwFormBuilt = true;
      return;
    }

    const isUnlocked = !!d.is_drying_unlocked;
    const temp = d.drying_temp_c ?? null;
    const rh   = d.drying_rh_pct ?? null;

    const TARGET_TEMP = isUnlocked ? (this._draftValue(this._editingPeriod === 'day' ? 'day_temp_c' : 'night_temp_c') ?? 15.5) : 15.5;
    const TARGET_RH   = 60.0;

    const tempOk = temp != null && Math.abs(temp - TARGET_TEMP) < 1.0;
    const rhOk   = rh   != null && Math.abs(rh   - TARGET_RH)   < 3.0;

    const tempClass = tempOk ? 'bg-green' : (temp != null ? 'bg-amber' : 'bg-gray');
    const rhClass   = rhOk   ? 'bg-green' : (rh   != null ? 'bg-amber' : 'bg-gray');

    const lockBanner = isUnlocked
      ? `<div class="chip-row" style="margin-bottom:10px;align-items:center">
          <span class="badge bg-amber">🔓 Custom Profile Active</span>
          <button class="hx-relock-btn" style="margin-left:auto;padding:6px 10px;border-radius:8px;border:1px solid var(--hx-border,#333);background:none;color:var(--hx-text);cursor:pointer;font-size:.75rem">🔒 Re-lock to 60/60</button>
        </div>`
      : `<div class="chip-row" style="margin-bottom:10px;align-items:center">
          <span class="badge bg-blue">🔒 Locked: Standard Cure Profile — 15.5°C / 60% RH</span>
          <button class="hx-unlock-btn" style="margin-left:auto;padding:6px 10px;border-radius:8px;border:1px solid var(--hx-border,#333);background:none;color:var(--hx-text);cursor:pointer;font-size:.75rem">🔓 Unlock</button>
        </div>`;

    let profileEditorHtml = '';
    if (isUnlocked) {
      const period = this._editingPeriod;
      const isDay = period === 'day';
      const tempKey = isDay ? 'day_temp_c' : 'night_temp_c';
      const vpdMinKey = isDay ? 'day_vpd_min' : 'night_vpd_min';
      const vpdMaxKey = isDay ? 'day_vpd_max' : 'night_vpd_max';
      const tempAnchor = this._draftValue(tempKey);
      const vpdMin = this._draftValue(vpdMinKey);
      const vpdMax = this._draftValue(vpdMaxKey);
      profileEditorHtml = `
      <div class="card">
        <div class="card-title">📊 Custom Drying Profile</div>
        <div class="hx-period-toggle" style="display:flex;gap:6px;margin-bottom:12px">
          <button class="period-btn ${isDay ? 'active' : ''}" data-period="day"
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
            background:${isDay ? 'var(--hx-blue,#209cee)' : 'none'};color:${isDay ? '#fff' : 'var(--hx-text)'};font-weight:600">☀️ Day</button>
          <button class="period-btn ${!isDay ? 'active' : ''}" data-period="night"
            style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border,#333);cursor:pointer;
            background:${!isDay ? 'var(--hx-blue,#209cee)' : 'none'};color:${!isDay ? '#fff' : 'var(--hx-text)'};font-weight:600">🌙 Night</button>
        </div>
        <div class="sec">VPD Range</div>
        <div class="slider-row">
          <span class="slider-lbl">Min</span>
          <input type="range" id="drying-vpd-min" min="0.3" max="1.8" step="0.05" value="${fn(vpdMin,2)}"/>
          <span class="slider-val" id="drying-vpd-min-val">${fVPD(vpdMin)}</span>
        </div>
        <div class="slider-row">
          <span class="slider-lbl">Max</span>
          <input type="range" id="drying-vpd-max" min="0.3" max="1.8" step="0.05" value="${fn(vpdMax,2)}"/>
          <span class="slider-val" id="drying-vpd-max-val">${fVPD(vpdMax)}</span>
        </div>
        <div class="sec">Temperature Anchor</div>
        <div class="slider-row">
          <input type="range" id="drying-temp-anchor" min="5" max="25" step="0.5" value="${fn(tempAnchor,1)}"/>
          <span class="slider-val" id="drying-temp-anchor-val">${fT(tempAnchor)}</span>
        </div>
      </div>`;
    }

    this.shadowRoot.innerHTML = `
      <style>${BASE_CSS}:host{display:block;}</style>
      <div class="card">
        <div class="card-title" style="display:flex;align-items:center">🍃 ${d.drying_zone_name || 'Drying Room'} — 60/60 Cure Profile ${_gearBtnHtml()}</div>
        ${lockBanner}
        <div class="chip-row" style="margin-bottom:10px">
          <span class="badge bg-blue">Target ${fT(TARGET_TEMP)}</span>
          <span class="badge bg-blue">Target ${TARGET_RH}% RH</span>
          ${tempOk && rhOk ? '<span class="badge bg-green">✓ On Profile</span>' : '<span class="badge bg-amber">⚠ Deviating</span>'}
        </div>
        <div class="g2">
          <div class="stat-cell">
            <div class="val"><span class="badge ${tempClass}">${fT(temp)}</span></div>
            <div class="lbl">Temperature</div>
            <div style="font-size:.65rem;color:var(--hx-text2);margin-top:3px">
              Δ ${temp != null ? fn(Math.abs(temp-TARGET_TEMP),1) + '°C' : '—'} from target
            </div>
          </div>
          <div class="stat-cell">
            <div class="val"><span class="badge ${rhClass}">${fRH(rh)}</span></div>
            <div class="lbl">Relative Humidity</div>
            <div style="font-size:.65rem;color:var(--hx-text2);margin-top:3px">
              Δ ${rh != null ? fn(Math.abs(rh-TARGET_RH),1) + '%' : '—'} from target
            </div>
          </div>
        </div>
        <hr/>
        <div class="metric-row">
          <span class="metric-label">Dehumidifier</span>
          <span class="metric-val">${d.drying_dehumid_on ? '🟢 Active' : '⚫ Idle'}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Exhaust Fan</span>
          <span class="metric-val">${fPct(d.drying_exhaust_pct)} (25% cyclic)</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Circulation Fan</span>
          <span class="metric-val">${fPct(d.drying_circ_pct)} (indirect, 40%)</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">HVAC Mode</span>
          <span class="metric-val">${d.drying_hvac_mode || '—'}</span>
        </div>
        <hr/>
        <div style="font-size:.68rem;color:var(--hx-text2);margin-bottom:4px">
          Zone 2's own exhaust (separate from this dedicated room's fixed 25%/40% airflow above):
        </div>
        ${_dryingOverrideStatusHtml(d)}
      </div>
      ${profileEditorHtml}
      <div class="card">
        <div class="card-title">ℹ️ 60/60 Profile</div>
        <p style="font-size:.8rem;color:var(--hx-text2);line-height:1.5">
          The 60/60 cure protocol maintains <strong style="color:var(--hx-text)">${fT(15.5)} / 60% RH</strong>
          for slow terpene preservation and moisture equalisation.
          Exhaust runs at a gentle <strong style="color:var(--hx-text)">25%</strong> to exchange air
          without disturbing the humidity gradient. Indirect circulation fans run at
          <strong style="color:var(--hx-text)">40%</strong> to prevent hot spots without
          direct airflow over product. ${isUnlocked ? 'Custom profiles override these fixed values while unlocked.' : ''}
        </p>
      </div>`;

    _bindGearBtn(this.shadowRoot, this);

    const unlockBtn = this.shadowRoot.querySelector('.hx-unlock-btn');
    if (unlockBtn) unlockBtn.addEventListener('click', () => this._toggleDryingLock(true));
    const relockBtn = this.shadowRoot.querySelector('.hx-relock-btn');
    if (relockBtn) relockBtn.addEventListener('click', () => this._toggleDryingLock(false));

    if (isUnlocked) {
      this.shadowRoot.querySelectorAll('.period-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          this._editingPeriod = btn.dataset.period;
          this._render();
        });
      });
      const period = this._editingPeriod;
      const isDay = period === 'day';
      const tempKey = isDay ? 'day_temp_c' : 'night_temp_c';
      const vpdMinKey = isDay ? 'day_vpd_min' : 'night_vpd_min';
      const vpdMaxKey = isDay ? 'day_vpd_max' : 'night_vpd_max';

      const vMinSl = this.shadowRoot.querySelector('#drying-vpd-min');
      const vMinVal = this.shadowRoot.querySelector('#drying-vpd-min-val');
      if (vMinSl) {
        vMinSl.addEventListener('input', e => { vMinVal.textContent = fVPD(parseFloat(e.target.value)); });
        vMinSl.addEventListener('change', e => {
          this._stageDraft[vpdMinKey] = parseFloat(e.target.value);
          this._saveDryingTargets();
        });
      }
      const vMaxSl = this.shadowRoot.querySelector('#drying-vpd-max');
      const vMaxVal = this.shadowRoot.querySelector('#drying-vpd-max-val');
      if (vMaxSl) {
        vMaxSl.addEventListener('input', e => { vMaxVal.textContent = fVPD(parseFloat(e.target.value)); });
        vMaxSl.addEventListener('change', e => {
          this._stageDraft[vpdMaxKey] = parseFloat(e.target.value);
          this._saveDryingTargets();
        });
      }
      const tSl = this.shadowRoot.querySelector('#drying-temp-anchor');
      const tVal = this.shadowRoot.querySelector('#drying-temp-anchor-val');
      if (tSl) {
        tSl.addEventListener('input', e => { tVal.textContent = fT(parseFloat(e.target.value)); });
        tSl.addEventListener('change', e => {
          this._stageDraft[tempKey] = parseFloat(e.target.value);
          this._saveDryingTargets();
        });
      }
    }
  }
  connectedCallback() { this._render(); }
}
customElements.define('helix-tab-drying', HelixTabDrying);

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Settings & Configuration Hub  <helix-tab-settings>
// ─────────────────────────────────────────────────────────────────────────────

class HelixTabSettings extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._section = 'modules'; // modules | zone2 | calibration | safety | drying | energy | learning
    // Energy & ROI's gear-icon edit mode — the only section here that uses
    // the hardware-mapping form pattern, so these flags only ever matter
    // when this._section === 'energy'.
    this._isEditingHardware = false;
    this._hwFormBuilt = false;
    // Environmental Learning (Part 10) — fetched on-demand when that
    // section is selected, since it needs live server-side state
    // (learning_state, active_test, per-zone eligibility) beyond the
    // regular coordinator data push.
    this._learningStatus = null;
    this._learningActionStatus = '';
  }

  set hass(h) { this._hass = h; }
  set data(d) { this._data = d; this._render(); }

  _svc(domain, service, data) {
    if (this._hass) this._hass.callService(domain, service, data);
  }

  // Reads Zone 2 width/depth/height/plant-count straight from the DOM and
  // saves them in one explicit batch — these are static config-entry fields,
  // not live HA entities, so there's nothing to auto-save on drag.
  async _saveZone2Dimensions() {
    const q = (id) => this.shadowRoot.querySelector(id);
    const fields = {
      zone2_width_m: parseFloat(q('#z2-width').value),
      zone2_depth_m: parseFloat(q('#z2-depth').value),
      zone2_height_m: parseFloat(q('#z2-height').value),
      zone2_plant_count: parseInt(q('#z2-plants').value, 10),
    };

    const entryId = (this._data || {}).entry_id;
    const statusEl = this.shadowRoot.querySelector('#zone2-dims-save-status');
    if (!this._hass || !entryId) {
      if (statusEl) statusEl.textContent = '❌ Save failed — no config entry found';
      return;
    }
    if (statusEl) statusEl.textContent = 'Saving…';
    try {
      await this._hass.callWS({
        type: 'helix_cultivate/update_settings_fields',
        entry_id: entryId,
        fields,
      });
      if (statusEl) statusEl.textContent = '✅ Saved';
    } catch (e) {
      console.error('Helix Cultivate: zone2 dimensions save failed', e);
      if (statusEl) statusEl.textContent = '❌ Save failed — see console';
    }
  }

  _sectionBtn(id, label) {
    const active = this._section === id;
    return `<button class="sec-btn ${active ? 'active' : ''}" data-sec="${id}">${label}</button>`;
  }

  _offsetRow(label, key, value) {
    const v = value ?? 0;
    return `
      <div class="metric-row" style="gap:8px;flex-wrap:wrap">
        <span class="metric-label" style="min-width:160px">${label}</span>
        <div style="display:flex;align-items:center;gap:6px;margin-left:auto">
          <button class="adj-btn" data-key="${key}" data-step="-0.1" style="padding:3px 8px;font-size:.8rem;
            border-radius:5px;border:1px solid var(--hx-border);background:var(--hx-surface2);
            color:var(--hx-text);cursor:pointer">−</button>
          <span style="font-size:.85rem;font-weight:600;min-width:48px;text-align:center" id="cal-${key}">
            ${v >= 0 ? '+' : ''}${fn(v,1)}</span>
          <button class="adj-btn" data-key="${key}" data-step="0.1" style="padding:3px 8px;font-size:.8rem;
            border-radius:5px;border:1px solid var(--hx-border);background:var(--hx-surface2);
            color:var(--hx-text);cursor:pointer">+</button>
        </div>
      </div>`;
  }

  _renderModules() {
    const d = this._data || {};
    const condEnabled  = d.enable_conditioning_room  ?? (d.topology === 'coordinated');
    const dryEnabled   = d.enable_drying_environment ?? false;

    return `
      <div class="card">
        <div class="card-title">📦 Module Registry</div>
        <div class="toggle-row">
          <div>
            <div class="toggle-lbl">🌬 Enable Conditioning Room (Zone 1)</div>
            <div style="font-size:.72rem;color:var(--hx-text2);margin-top:2px">
              Activates Zone 1 climate control and Conditioning Room tab
            </div>
          </div>
          <label class="sw">
            <input type="checkbox" id="tog-conditioning" ${condEnabled ? 'checked' : ''}/>
            <span class="sw-track"></span>
            <span class="sw-thumb"></span>
          </label>
        </div>
        <hr/>
        <div class="toggle-row">
          <div>
            <div class="toggle-lbl">🍃 Enable Drying Environment (60/60)</div>
            <div style="font-size:.72rem;color:var(--hx-text2);margin-top:2px">
              Activates 60/60 cure profile control and Drying Environment tab
            </div>
          </div>
          <label class="sw">
            <input type="checkbox" id="tog-drying" ${dryEnabled ? 'checked' : ''}/>
            <span class="sw-track"></span>
            <span class="sw-thumb"></span>
          </label>
        </div>
        <hr/>
        <p style="font-size:.75rem;color:var(--hx-text2);margin-top:6px;line-height:1.5">
          ⚠ Toggling modules restarts the integration to apply hardware routing changes.
          Changes take effect after HA applies the updated options.
        </p>
      </div>`;
  }

  _renderZone2() {
    const d = this._data || {};
    return `
      <div class="card">
        <div class="card-title">🌱 Zone 2 — Primary Grow Space Config</div>
        <div class="sec">Dimensions</div>
        <div class="g3">
          <div>
            <div style="font-size:.72rem;color:var(--hx-text2)">Width (m)</div>
            <input type="number" id="z2-width" min="0.1" max="20" step="0.1"
              value="${d.zone2_width_m ?? 1.2}" style="width:80px;margin-top:4px"/>
          </div>
          <div>
            <div style="font-size:.72rem;color:var(--hx-text2)">Depth (m)</div>
            <input type="number" id="z2-depth" min="0.1" max="20" step="0.1"
              value="${d.zone2_depth_m ?? 1.2}" style="width:80px;margin-top:4px"/>
          </div>
          <div>
            <div style="font-size:.72rem;color:var(--hx-text2)">Height (m)</div>
            <input type="number" id="z2-height" min="0.5" max="6" step="0.1"
              value="${d.zone2_height_m ?? 2.0}" style="width:80px;margin-top:4px"/>
          </div>
        </div>
        <div class="sec">Plant Count</div>
        <input type="number" id="z2-plants" min="1" max="100" step="1"
          value="${d.zone2_plant_count ?? 4}" style="width:80px"/>
        <div style="display:flex;align-items:center;gap:10px;margin-top:12px">
          <button id="save-zone2-dims-btn" style="padding:9px 16px;border-radius:8px;border:none;
            background:var(--hx-blue,#209cee);color:#fff;font-weight:600;cursor:pointer">💾 Save Dimensions</button>
          <span id="zone2-dims-save-status" style="font-size:.75rem;color:var(--hx-text2)"></span>
        </div>
        <div class="sec">Sunrise / Sunset Ramps</div>
        <div class="slider-row">
          <span class="slider-lbl">Sunrise Ramp</span>
          <input type="range" id="sunrise-ramp" min="0" max="60" step="1" value="${d.sunrise_ramp_min ?? 20}"/>
          <span class="slider-val" id="sunrise-val">${d.sunrise_ramp_min ?? 20} min</span>
        </div>
      </div>`;
  }

  _renderCalibration() {
    const d = this._data || {};
    return `
      <div class="card">
        <div class="card-title">🔬 Sensor Calibration — Primary Grow Space</div>
        ${this._offsetRow('Primary Temp Offset', 'primary_temp_offset', d.primary_temp_offset)}
        ${this._offsetRow('Primary Humidity Offset', 'primary_humidity_offset', d.primary_humidity_offset)}
        ${this._offsetRow('Upper Canopy Temp Offset', 'upper_temp_offset', d.upper_temp_offset)}
        ${this._offsetRow('Upper Canopy RH Offset', 'upper_humidity_offset', d.upper_humidity_offset)}
        ${this._offsetRow('Mid Canopy Temp Offset', 'mid_temp_offset', d.mid_temp_offset)}
        ${this._offsetRow('Mid Canopy RH Offset', 'mid_humidity_offset', d.mid_humidity_offset)}
        ${this._offsetRow('Lower Canopy Temp Offset', 'lower_temp_offset', d.lower_temp_offset)}
        ${this._offsetRow('Lower Canopy RH Offset', 'lower_humidity_offset', d.lower_humidity_offset)}
      </div>
      ${(d.enable_conditioning_room ?? (d.topology === 'coordinated')) ? `
      <div class="card">
        <div class="card-title">🔬 Sensor Calibration — Conditioning Room</div>
        ${this._offsetRow('Lung Temp Offset', 'lung_temp_offset', d.lung_temp_offset)}
        ${this._offsetRow('Lung Humidity Offset', 'lung_humidity_offset', d.lung_humidity_offset)}
      </div>` : ''}
      ${(d.enable_drying_environment) ? `
      <div class="card">
        <div class="card-title">🔬 Sensor Calibration — Drying Room</div>
        ${this._offsetRow('Drying Temp Offset', 'drying_temp_offset', d.drying_temp_offset)}
        ${this._offsetRow('Drying Humidity Offset', 'drying_humidity_offset', d.drying_humidity_offset)}
      </div>` : ''}`;
  }

  _renderSafety() {
    const d = this._data || {};
    return `
      <div class="card">
        <div class="card-title">🛡 Safety Interlocks</div>
        <div class="sec">Temperature Ceilings</div>
        <div class="slider-row">
          <span class="slider-lbl">High Temp Cutoff</span>
          <input type="range" id="safe-hi-temp" min="26" max="40" step="0.5" value="${d.safety_high_temp_c ?? 32}"/>
          <span class="slider-val" id="safe-hi-temp-val">${fT(d.safety_high_temp_c ?? 32)}</span>
        </div>
        <div class="slider-row">
          <span class="slider-lbl">Low Temp Cutoff</span>
          <input type="range" id="safe-lo-temp" min="5" max="20" step="0.5" value="${d.safety_low_temp_c ?? 15}"/>
          <span class="slider-val" id="safe-lo-temp-val">${fT(d.safety_low_temp_c ?? 15)}</span>
        </div>
        <div class="sec">Humidity Ceilings</div>
        <div class="slider-row">
          <span class="slider-lbl">High RH Cutoff</span>
          <input type="range" id="safe-hi-rh" min="60" max="95" step="1" value="${d.safety_high_rh_pct ?? 85}"/>
          <span class="slider-val" id="safe-hi-rh-val">${fRH(d.safety_high_rh_pct ?? 85)}</span>
        </div>
        <div class="slider-row">
          <span class="slider-lbl">Low RH Cutoff</span>
          <input type="range" id="safe-lo-rh" min="15" max="50" step="1" value="${d.safety_low_rh_pct ?? 30}"/>
          <span class="slider-val" id="safe-lo-rh-val">${fRH(d.safety_low_rh_pct ?? 30)}</span>
        </div>
        <div class="sec">Sensor Dropout Failsafe</div>
        <div class="slider-row">
          <span class="slider-lbl">Dropout Timeout</span>
          <input type="range" id="dropout-min" min="5" max="120" step="1" value="${d.sensor_dropout_min ?? 30}"/>
          <span class="slider-val" id="dropout-min-val">${d.sensor_dropout_min ?? 30} min</span>
        </div>
        <div class="sec">Dew Point / Condensation Override</div>
        <div class="slider-row">
          <span class="slider-lbl">Margin</span>
          <input type="range" id="dew-point-margin-slider" min="0.5" max="5" step="0.1" value="${d.dew_point_margin_c ?? 2.0}"/>
          <span class="slider-val" id="dew-point-margin-val">${fn(d.dew_point_margin_c ?? 2.0, 1)}°C</span>
        </div>
        <div style="font-size:.7rem;color:var(--hx-text2);margin-top:2px">
          If leaf temperature comes within this margin of the calculated dew point for a
          sustained period, exhaust is forced to 100% and lung-room heating is forced on —
          the same "always wins" hard override as thermal runaway, targeting the actual
          mechanism behind botrytis/powdery mildew risk.
        </div>
      </div>`;
  }

  // ── Environmental Learning (v1.4.0 Parts 7-10) ──────────────────────────────

  async _fetchLearningStatus() {
    if (!this._hass) return;
    try {
      this._learningStatus = await this._hass.callWS({ type: 'helix_cultivate/get_learning_status' });
    } catch (e) {
      console.warn('Helix Cultivate: could not fetch learning status', e);
      this._learningStatus = null;
    }
    this._render();
  }

  _renderLearningZoneCard(zoneKey, label, occupied, eligible) {
    const status = this._learningStatus || {};
    const active = status.active_test;
    const testRunningHere = active && active.zone === zoneKey;
    return `
      <div class="card card-sm">
        <div class="card-title">${label}</div>
        <div style="font-size:.75rem;color:var(--hx-text2);margin-bottom:8px">
          ${occupied
            ? 'Occupied — Live Actuator Response Testing only.'
            : 'Unoccupied — both Deep Calibration and Live Actuator Response Testing available.'}
        </div>
        ${testRunningHere ? `
          <div style="font-size:.75rem;background:rgba(32,156,238,.12);border-radius:6px;padding:6px;margin-bottom:8px">
            🔬 ${active.type === 'deep_calibration' ? 'Deep Calibration' : 'Live Actuator Test'} in progress…
          </div>
        ` : `
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            <button class="learning-start-btn" data-zone="${zoneKey}" data-type="deep_calibration"
              ${occupied || !eligible ? 'disabled' : ''}
              style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-border);
              background:none;color:var(--hx-text);cursor:pointer;font-size:.75rem;
              ${occupied || !eligible ? 'opacity:.4;cursor:not-allowed' : ''}">Deep Calibration</button>
            <button class="learning-start-btn" data-zone="${zoneKey}" data-type="live_actuator"
              style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--hx-accent);
              background:none;color:var(--hx-accent);cursor:pointer;font-size:.75rem">Live Actuator Test</button>
          </div>
        `}
      </div>`;
  }

  _renderLearning() {
    const d = this._data || {};
    const enabled = d.thermal_learning_enabled === true;

    if (!enabled) {
      return `
        <div class="card">
          <div class="card-title">🧠 Environmental Learning</div>
          <div style="font-size:.8rem;color:var(--hx-text2);margin-bottom:12px;line-height:1.5">
            Opt-in, advanced layer that correlates external conditions, time-of-day, and lighting
            against actuator behavior to eventually refine predictive pre-conditioning with real,
            site-specific data. Off by default — while off, nothing runs in the background at all.
          </div>
          <div class="toggle-row">
            <span class="toggle-lbl">Enable Environmental Learning</span>
            <label class="sw">
              <input type="checkbox" id="learning-master-toggle" />
              <span class="sw-track"></span>
              <span class="sw-thumb"></span>
            </label>
          </div>
        </div>`;
    }

    const status = this._learningStatus || {};
    const stateLabel = status.learning_state === 'active' ? '✅ Active' : '📖 Learning';
    const startedAt = status.started_at ? new Date(status.started_at).toLocaleDateString() : '—';

    return `
      <div class="card">
        <div class="card-title">🧠 Environmental Learning</div>
        <div class="toggle-row">
          <span class="toggle-lbl">Enable Environmental Learning</span>
          <label class="sw">
            <input type="checkbox" id="learning-master-toggle" checked />
            <span class="sw-track"></span>
            <span class="sw-thumb"></span>
          </label>
        </div>
        <div class="metric-row">
          <span class="metric-label">State</span>
          <span class="metric-val">${stateLabel}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Started</span>
          <span class="metric-val">${startedAt}</span>
        </div>
        <div class="sec">Learning Duration</div>
        <div class="slider-row">
          <span class="slider-lbl">Days</span>
          <input type="range" id="learning-duration-slider" min="7" max="30" step="1"
            value="${d.thermal_learning_duration_days ?? 18}"/>
          <span class="slider-val" id="learning-duration-val">${d.thermal_learning_duration_days ?? 18}d</span>
        </div>
        <div style="font-size:.7rem;color:var(--hx-text2);margin-top:2px">
          Graduates to Active unconditionally after this many days, regardless of what conditions
          were observed — the model keeps refitting indefinitely afterward, it never freezes.
        </div>
        <div id="learning-action-status" style="font-size:.75rem;color:var(--hx-text2);margin-top:8px">
          ${this._learningActionStatus}
        </div>
      </div>
      <div class="sec">Per-Zone Testing</div>
      <div class="g3">
        ${this._renderLearningZoneCard('zone2', '🌱 Primary Grow Space', status.zone2_occupied, true)}
        ${status.drying_enabled ? this._renderLearningZoneCard('drying', '🍃 Drying Room', status.drying_occupied, true) : ''}
        ${this._renderLearningZoneCard('conditioning', '🌬 Conditioning Room', false, status.conditioning_eligible !== false)}
      </div>
      <div class="card" style="margin-top:10px">
        <div class="card-title">📡 Optional Data Export</div>
        <div style="font-size:.7rem;color:var(--hx-text2);margin-bottom:8px">
          Best-effort, one-way mirror to an InfluxDB (or InfluxDB-line-protocol-compatible, e.g.
          VictoriaMetrics) endpoint for building your own Grafana dashboards. Never a dependency —
          the core learning system is unaffected if this is unset or unreachable.
        </div>
        <div class="toggle-row">
          <span class="toggle-lbl">Enable Export</span>
          <label class="sw">
            <input type="checkbox" id="learning-export-toggle" ${d.thermal_learning_export_enabled ? 'checked' : ''} />
            <span class="sw-track"></span>
            <span class="sw-thumb"></span>
          </label>
        </div>
        <input type="text" id="learning-export-url" placeholder="http://influxdb.local:8086/api/v2/write?..."
          value="${d.thermal_learning_export_url || ''}"
          style="width:100%;padding:8px;border-radius:8px;margin-top:6px;
          border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
      </div>`;
  }

  _renderEnergy() {
    const h = this._hass;
    const d = this._data || {};

    const zone1On = d.em_zone1_enabled !== false;
    const zone2On = d.em_zone2_enabled !== false;
    const dryingOn = d.em_drying_enabled !== false;

    // Disabled zones are fully absent from the live dashboard — not shown-
    // disabled — same pattern as canopy sensor/fan tier toggles. Global has
    // no toggle and is never in this list; it gets its own 2-card summary
    // below instead of a raw 4-slot grid (2.4).
    const emZones = [
      { on: zone2On,  label: '🌱 Primary Grow Space', keys: ['em_zone2_s1','em_zone2_s2','em_zone2_s3','em_zone2_s4'] },
      { on: zone1On,  label: '🌬 Conditioning Room',  keys: ['em_zone1_s1','em_zone1_s2','em_zone1_s3','em_zone1_s4'] },
      { on: dryingOn, label: '🍃 Drying Room',        keys: ['em_drying_s1','em_drying_s2','em_drying_s3','em_drying_s4'] },
    ];

    let totalW = 0;
    const emRows = emZones.filter(z => z.on).map(zone => {
      const cells = zone.keys.map(k => {
        const entityId = d[k] ?? null;
        let w = null;
        if (entityId && h && h.states[entityId]) {
          const raw = parseFloat(h.states[entityId].state);
          if (!isNaN(raw)) { w = raw; totalW += raw; }
        }
        return `<div class="stat-cell">
          <div class="val" style="font-size:.88rem">${w != null ? w.toFixed(0)+'W' : '—'}</div>
          <div class="lbl" style="font-size:.6rem;word-break:break-all">${entityId ? entityId.split('.').pop() : 'unset'}</div>
        </div>`;
      }).join('');
      return `<div style="margin-bottom:10px">
          <div class="card-title" style="font-size:.78rem;margin-bottom:4px">${zone.label}</div>
          <div class="g4">${cells}</div>
        </div>`;
    }).join('');

    // Global's own direct slots always contribute to Live Load, same as
    // they always contribute to the aggregate total server-side.
    ['em_global_s1','em_global_s2','em_global_s3','em_global_s4'].forEach(k => {
      const entityId = d[k] ?? null;
      if (entityId && h && h.states[entityId]) {
        const raw = parseFloat(h.states[entityId].state);
        if (!isNaN(raw)) totalW += raw;
      }
    });

    const tariffModeLabel = TARIFF_MODE_LABELS_JS[d.tariff_mode] || TARIFF_MODE_LABELS_JS.anytime;
    const rateDisplay = (d.tariff_mode ?? 'anytime') === 'anytime' && d.tariff_anytime_rate != null
      ? `<div><div style="font-size:.7rem;color:var(--hx-text2)">Rate (anytime)</div>
         <div style="font-size:.92rem;font-weight:700">$${fn(d.tariff_anytime_rate, 3)}/kWh</div></div>`
      : '';

    const previousCycleHtml = (d.previous_cycle_kwh != null && d.previous_cycle_cost_usd != null)
      ? `<div><div style="font-size:.7rem;color:var(--hx-text2)">Previous Cycle</div>
          <div style="font-size:.92rem;font-weight:700">${fn(d.previous_cycle_kwh,1)} kWh · $${fn(d.previous_cycle_cost_usd,2)}</div></div>`
      : `<div><div style="font-size:.7rem;color:var(--hx-text2)">Previous Cycle</div>
          <div style="font-size:.85rem;color:var(--hx-text2)">No reset yet</div></div>`;

    return `
      <div class="card">
        <div class="card-title" style="display:flex;align-items:center">⚡ Energy & ROI ${_gearBtnHtml()}</div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:14px;align-items:center">
          <div>
            <div style="font-size:.7rem;color:var(--hx-text2)">Tariff Mode</div>
            <div style="font-size:.92rem;font-weight:700">${tariffModeLabel}</div>
          </div>
          ${rateDisplay}
          <div>
            <div style="font-size:.7rem;color:var(--hx-text2)">Live Load</div>
            <div style="font-size:1.1rem;font-weight:800;color:var(--hx-amber)">${totalW.toFixed(0)} W</div>
          </div>
          <div>
            <div style="font-size:.7rem;color:var(--hx-text2)">Cycle Cost</div>
            <div style="font-size:1.1rem;font-weight:800;color:var(--hx-green)">${d.cycle_cost ?? '—'}</div>
          </div>
          ${previousCycleHtml}
        </div>
        ${emRows}
        <div style="margin-bottom:10px">
          <div class="card-title" style="font-size:.78rem;margin-bottom:4px">🌐 Global / Infrastructure</div>
          <div class="g2">
            <div class="stat-cell">
              <div class="val" style="font-size:1.05rem">${fn(d.cycle_kwh ?? 0, 2)} kWh</div>
              <div class="lbl">Total kWh Used</div>
            </div>
            <div class="stat-cell">
              <div class="val" style="font-size:1.05rem">${d.cycle_cost ?? '—'}</div>
              <div class="lbl">Total Cost ($)</div>
            </div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:10px;margin-top:12px">
          <button id="energy-reset-btn" style="padding:9px 16px;border-radius:8px;border:1px solid var(--hx-border);
            background:none;color:var(--hx-text);font-weight:600;cursor:pointer">♻ Reset Cycle Totals</button>
          <span id="energy-reset-status" style="font-size:.75rem;color:var(--hx-text2)"></span>
        </div>
      </div>`;
  }

  // ── Energy & ROI gear-icon edit form ────────────────────────────────────
  // Same hardware-mapping-form pattern as every other zone (_renderHwPicker/
  // _bindHwPicker/_gearBtnHtml/_bindGearBtn) — hwKeys is passed empty here
  // since the per-zone grouping (with its enable toggles interleaved) needs
  // custom layout, so every picker row + toggle is built directly into
  // extraHtml instead; _bindHwPicker still does the entity-picker wiring by
  // matching .hw-entity-slot elements wherever they appear.
  _renderEnergyEditForm() {
    const d = this._data || {};
    const hwMap = d.hw_map || {};
    const zone1On = d.em_zone1_enabled !== false;
    const zone2On = d.em_zone2_enabled !== false;
    const dryingOn = d.em_drying_enabled !== false;
    const tariffMode = TARIFF_MODE_OPTIONS_JS.includes(d.tariff_mode) ? d.tariff_mode : 'anytime';

    const zoneGroup = (title, emKeys, toggleKey, checked) => `
      <div class="sec">${title}</div>
      ${_hwLayerToggleRow(toggleKey, 'Enable EM Monitoring', checked)}
      ${emKeys.map(k => _hwPickerRow(k, hwMap[k.key] || '')).join('')}`;

    const energyExtraHtml = `
      ${zoneGroup('🌱 Primary Grow Space', ENERGY_ZONE2_EM_KEYS, 'em_zone2_enabled', zone2On)}
      ${zoneGroup('🌬 Conditioning Room', ENERGY_ZONE1_EM_KEYS, 'em_zone1_enabled', zone1On)}
      ${zoneGroup('🍃 Drying Room', ENERGY_DRYING_EM_KEYS, 'em_drying_enabled', dryingOn)}
      <div class="sec">🌐 Global / Infrastructure</div>
      <div style="font-size:.7rem;color:var(--hx-text2);margin-bottom:8px">
        Always shown and always included in the total — for genuinely global-only
        loads like a main incoming supply meter. No enable toggle.
      </div>
      ${ENERGY_GLOBAL_EM_KEYS.map(k => _hwPickerRow(k, hwMap[k.key] || '')).join('')}

      <div class="sec">Tariff Mode</div>
      <select id="energy-tariff-mode-select" style="width:100%;padding:8px;border-radius:8px;
        border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)">
        ${TARIFF_MODE_OPTIONS_JS.map(opt => `<option value="${opt}" ${tariffMode === opt ? 'selected' : ''}>${TARIFF_MODE_LABELS_JS[opt]}</option>`).join('')}
      </select>

      <div id="energy-tariff-anytime-fields" ${tariffMode === 'anytime' ? '' : 'hidden'}>
        <div class="metric-row">
          <span class="metric-label">Rate ($/kWh)</span>
          <input type="number" id="energy-tariff-anytime-rate" min="0" step="0.001"
            value="${d.tariff_anytime_rate ?? 0.28}" style="padding:5px;border-radius:6px;
            border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
        </div>
      </div>
      <div id="energy-tariff-peak-fields" ${tariffMode === 'anytime' ? 'hidden' : ''}>
        <div class="sec">Peak</div>
        <div class="metric-row">
          <span class="metric-label">Rate ($/kWh)</span>
          <input type="number" id="energy-tariff-peak-rate" min="0" step="0.001"
            value="${d.tariff_peak_rate ?? 0.45}" style="padding:5px;border-radius:6px;
            border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
        </div>
        <div class="metric-row">
          <span class="metric-label">Window</span>
          <div style="display:flex;gap:6px">
            <input type="time" id="energy-tariff-peak-start" value="${d.tariff_peak_start || '07:00'}"
              style="padding:5px;border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
            <input type="time" id="energy-tariff-peak-end" value="${d.tariff_peak_end || '21:00'}"
              style="padding:5px;border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
          </div>
        </div>
      </div>
      <div id="energy-tariff-shoulder-fields" ${tariffMode === 'triple' ? '' : 'hidden'}>
        <div class="sec">Shoulder</div>
        <div class="metric-row">
          <span class="metric-label">Rate ($/kWh)</span>
          <input type="number" id="energy-tariff-shoulder-rate" min="0" step="0.001"
            value="${d.tariff_shoulder_rate ?? 0.30}" style="padding:5px;border-radius:6px;
            border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
        </div>
        <div class="metric-row">
          <span class="metric-label">Window</span>
          <div style="display:flex;gap:6px">
            <input type="time" id="energy-tariff-shoulder-start" value="${d.tariff_shoulder_start || '07:00'}"
              style="padding:5px;border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
            <input type="time" id="energy-tariff-shoulder-end" value="${d.tariff_shoulder_end || '10:00'}"
              style="padding:5px;border-radius:6px;border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
          </div>
        </div>
      </div>
      <div id="energy-tariff-offpeak-fields" ${tariffMode === 'anytime' ? 'hidden' : ''}>
        <div class="sec">Off-Peak</div>
        <div style="font-size:.7rem;color:var(--hx-text2);margin-bottom:4px">
          Applies to any time outside the window(s) above — no window of its own.
        </div>
        <div class="metric-row">
          <span class="metric-label">Rate ($/kWh)</span>
          <input type="number" id="energy-tariff-offpeak-rate" min="0" step="0.001"
            value="${d.tariff_offpeak_rate ?? 0.15}" style="padding:5px;border-radius:6px;
            border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text)"/>
        </div>
      </div>`;

    return _renderHwPicker([], hwMap, this._hass, 'Energy & ROI', energyExtraHtml);
  }

  _bindEnergyEditForm() {
    _bindHwPicker(this.shadowRoot, this, ENERGY_ALL_EM_KEYS, () => {
      const fields = {};
      this.shadowRoot.querySelectorAll('.hw-layer-toggle').forEach(el => {
        fields[el.dataset.layer] = el.checked;
      });
      const q = (id) => this.shadowRoot.querySelector(id);
      const modeSel = q('#energy-tariff-mode-select');
      fields.tariff_mode = modeSel ? modeSel.value : 'anytime';
      if (q('#energy-tariff-anytime-rate')) fields.tariff_anytime = parseFloat(q('#energy-tariff-anytime-rate').value);
      if (q('#energy-tariff-peak-rate')) fields.tariff_peak = parseFloat(q('#energy-tariff-peak-rate').value);
      if (q('#energy-tariff-peak-start')) fields.tariff_peak_start = q('#energy-tariff-peak-start').value;
      if (q('#energy-tariff-peak-end')) fields.tariff_peak_end = q('#energy-tariff-peak-end').value;
      if (q('#energy-tariff-shoulder-rate')) fields.tariff_shoulder = parseFloat(q('#energy-tariff-shoulder-rate').value);
      if (q('#energy-tariff-shoulder-start')) fields.tariff_shoulder_start = q('#energy-tariff-shoulder-start').value;
      if (q('#energy-tariff-shoulder-end')) fields.tariff_shoulder_end = q('#energy-tariff-shoulder-end').value;
      if (q('#energy-tariff-offpeak-rate')) fields.tariff_offpeak = parseFloat(q('#energy-tariff-offpeak-rate').value);
      return fields;
    });

    // Tariff mode show/hide — pure DOM toggle, no _render(), matching the
    // Supplemental Lighting mode-toggle lesson: a rebuild would call
    // _bindHwPicker again, which resets _pendingDevices and would wipe any
    // in-progress entity-picker selections elsewhere in this same form.
    const modeSel = this.shadowRoot.querySelector('#energy-tariff-mode-select');
    if (modeSel) {
      modeSel.addEventListener('change', () => {
        const mode = modeSel.value;
        const anytimeEl = this.shadowRoot.querySelector('#energy-tariff-anytime-fields');
        const peakEl = this.shadowRoot.querySelector('#energy-tariff-peak-fields');
        const shoulderEl = this.shadowRoot.querySelector('#energy-tariff-shoulder-fields');
        const offpeakEl = this.shadowRoot.querySelector('#energy-tariff-offpeak-fields');
        if (anytimeEl) anytimeEl.hidden = mode !== 'anytime';
        if (peakEl) peakEl.hidden = mode === 'anytime';
        if (shoulderEl) shoulderEl.hidden = mode !== 'triple';
        if (offpeakEl) offpeakEl.hidden = mode === 'anytime';
      });
    }
  }

  _renderDryingSettings() {
    const d = this._data || {};
    return `
      <div class="card">
        <div class="card-title">🍃 Drying Environment Settings</div>
        <div class="metric-row">
          <span class="metric-label">Fixed Temp Target</span>
          <span class="metric-val">15.5°C (locked)</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Fixed RH Target</span>
          <span class="metric-val">60% (locked)</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Exhaust Mode</span>
          <span class="metric-val">25% cyclic (fixed)</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Circulation Fan</span>
          <span class="metric-val">40% indirect (fixed)</span>
        </div>
        <hr/>
        <p style="font-size:.75rem;color:var(--hx-text2);line-height:1.5;margin-top:4px">
          All drying zone parameters are fixed by the 60/60 cure protocol.
          Hardware mapping (sensors, dehumidifier, fans, HVAC) is configured
          in the integration's Options Flow (⚙ three-dot menu on the integration card).
        </p>
      </div>`;
  }

  _render() {
    // Energy & ROI's gear-icon edit mode is a full takeover of this tab,
    // same as every other zone's gear-icon form — no section nav or other
    // cards alongside it while editing.
    if (this._isEditingHardware && this._section === 'energy') {
      if (this._hwFormBuilt) {
        // Form already open — a routine coordinator data push arrived
        // mid-edit. Skip the destructive rebuild so in-progress entity-
        // picker selections aren't torn down.
        return;
      }
      this.shadowRoot.innerHTML = `<style>${BASE_CSS}:host{display:block;}</style>`
        + this._renderEnergyEditForm();
      this._bindEnergyEditForm();
      this._hwFormBuilt = true;
      return;
    }

    const sectionContent = {
      modules:     this._renderModules(),
      zone2:       this._renderZone2(),
      calibration: this._renderCalibration(),
      safety:      this._renderSafety(),
      drying:      this._renderDryingSettings(),
      energy:      this._renderEnergy(),
      learning:    this._renderLearning(),
    }[this._section] || '';

    this.shadowRoot.innerHTML = `
      <style>
        ${BASE_CSS}
        :host { display: block; }
        .sec-nav { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 12px; }
        .sec-btn {
          padding: 7px 12px; font-size: .78rem; font-weight: 600;
          border: 1px solid var(--hx-border); background: var(--hx-surface2);
          color: var(--hx-text2); cursor: pointer; border-radius: 8px;
          transition: background .15s, color .15s;
        }
        .sec-btn.active { background: var(--hx-accent); color: #fff; border-color: var(--hx-accent); }
      </style>
      <div class="sec-nav">
        ${this._sectionBtn('modules',     '📦 Modules')}
        ${this._sectionBtn('zone2',       '🌱 Grow Space')}
        ${this._sectionBtn('calibration', '🔬 Calibration')}
        ${this._sectionBtn('safety',      '🛡 Safety')}
        ${this._sectionBtn('drying',      '🍃 Drying')}
        ${this._sectionBtn('energy',      '⚡ Energy & ROI')}
        ${this._sectionBtn('learning',    '🧠 Environmental Learning')}
      </div>
      ${sectionContent}
      <!-- Export / Import Config -->
      <div class="card" style="margin-top:16px">
        <div class="card-title">📤 Config Backup</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
          <button id="hx-export-btn" style="padding:7px 14px;font-size:.78rem;font-weight:600;
            border:1px solid var(--hx-accent);background:var(--hx-accent);color:#fff;
            cursor:pointer;border-radius:8px">⬇ Export JSON</button>
          <label style="padding:7px 14px;font-size:.78rem;font-weight:600;
            border:1px solid var(--hx-border);background:var(--hx-surface2);color:var(--hx-text2);
            cursor:pointer;border-radius:8px">
            ⬆ Import JSON
            <input type="file" id="hx-import-input" accept=".json" style="display:none">
          </label>
          <span id="hx-import-status" style="font-size:.72rem;color:var(--hx-text2)"></span>
        </div>
      </div>`;

    // Export config JSON
    const exportBtn = this.shadowRoot.querySelector('#hx-export-btn');
    if (exportBtn) {
      exportBtn.addEventListener('click', () => {
        const payload = JSON.stringify(this._data || {}, null, 2);
        const blob = new Blob([payload], { type: 'application/json' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href = url;
        a.download = `helix-cultivate-config-${new Date().toISOString().slice(0,10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
      });
    }

    // Import config JSON
    const importInput  = this.shadowRoot.querySelector('#hx-import-input');
    const importStatus = this.shadowRoot.querySelector('#hx-import-status');
    if (importInput) {
      importInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
          try {
            const parsed = JSON.parse(ev.target.result);
            this.dispatchEvent(new CustomEvent('config-import', {
              bubbles: true, composed: true, detail: { config: parsed }
            }));
            if (importStatus) importStatus.textContent = `✅ Imported ${file.name}`;
          } catch (_) {
            if (importStatus) importStatus.textContent = '❌ Invalid JSON file';
          }
        };
        reader.readAsText(file);
      });
    }

    // Section nav
    this.shadowRoot.querySelectorAll('.sec-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._section = btn.dataset.sec;
        if (this._section === 'learning') this._fetchLearningStatus();
        this._render();
      });
    });

    // Module toggles
    const condTog = this.shadowRoot.querySelector('#tog-conditioning');
    if (condTog) {
      condTog.addEventListener('change', e => {
        this.dispatchEvent(new CustomEvent('module-change', {
          bubbles: true, composed: true,
          detail: { key: 'enable_conditioning_room', value: e.target.checked }
        }));
      });
    }
    const dryTog = this.shadowRoot.querySelector('#tog-drying');
    if (dryTog) {
      dryTog.addEventListener('change', e => {
        this.dispatchEvent(new CustomEvent('module-change', {
          bubbles: true, composed: true,
          detail: { key: 'enable_drying_environment', value: e.target.checked }
        }));
      });
    }

    // Calibration ± buttons
    this.shadowRoot.querySelectorAll('.adj-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const key = btn.dataset.key;
        const step = parseFloat(btn.dataset.step);
        const display = this.shadowRoot.querySelector(`#cal-${key}`);
        if (display) {
          const current = parseFloat(display.textContent) || 0;
          const newVal = Math.round((current + step) * 10) / 10;
          display.textContent = `${newVal >= 0 ? '+' : ''}${fn(newVal, 1)}`;
          // Store in panel data for next render; actual persistence via options flow
          if (this._data) this._data[key] = newVal;
          this.dispatchEvent(new CustomEvent('calibration-change', {
            bubbles: true, composed: true, detail: { key, value: newVal }
          }));
        }
      });
    });

    // Zone 2 dimensions — explicit Save (static config, not a live entity)
    const saveZone2Btn = this.shadowRoot.querySelector('#save-zone2-dims-btn');
    if (saveZone2Btn) {
      saveZone2Btn.addEventListener('click', () => this._saveZone2Dimensions());
    }

    // Sunrise ramp
    const sunriseRamp = this.shadowRoot.querySelector('#sunrise-ramp');
    const sunriseVal  = this.shadowRoot.querySelector('#sunrise-val');
    if (sunriseRamp) {
      sunriseRamp.addEventListener('input', e => {
        if (sunriseVal) sunriseVal.textContent = `${e.target.value} min`;
      });
      sunriseRamp.addEventListener('change', e => {
        if (this._hass) this._hass.callService('number', 'set_value', {
          entity_id: 'number.helix_cultivate_sunrise_ramp_min', value: parseFloat(e.target.value)
        });
      });
    }

    // Safety sliders (Part 1) — each now has a live number entity (built to
    // match the existing heater_cutoff/thermal_runaway pattern) to actually
    // persist to; previously these only updated the on-screen label.
    const safetySliders = [
      ['#safe-hi-temp', '#safe-hi-temp-val', fT,   'number.helix_cultivate_safety_high_temp'],
      ['#safe-lo-temp', '#safe-lo-temp-val', fT,   'number.helix_cultivate_safety_low_temp'],
      ['#safe-hi-rh',   '#safe-hi-rh-val',   fRH,  'number.helix_cultivate_safety_high_rh'],
      ['#safe-lo-rh',   '#safe-lo-rh-val',   fRH,  'number.helix_cultivate_safety_low_rh'],
    ];
    for (const [slId, valId, fmt, entityId] of safetySliders) {
      const sl = this.shadowRoot.querySelector(slId);
      const vl = this.shadowRoot.querySelector(valId);
      if (!sl) continue;
      sl.addEventListener('input', e => { if (vl) vl.textContent = fmt(parseFloat(e.target.value)); });
      sl.addEventListener('change', e => this._svc('number', 'set_value', {
        entity_id: entityId, value: parseFloat(e.target.value)
      }));
    }
    const dropSl = this.shadowRoot.querySelector('#dropout-min');
    const dropVl = this.shadowRoot.querySelector('#dropout-min-val');
    if (dropSl) {
      dropSl.addEventListener('input', e => { if (dropVl) dropVl.textContent = `${e.target.value} min`; });
      dropSl.addEventListener('change', e => this._svc('number', 'set_value', {
        entity_id: 'number.helix_cultivate_sensor_dropout_min', value: parseFloat(e.target.value)
      }));
    }

    // Dew point margin — persists via the explicit-Save/update_settings_fields
    // draft-config path rather than a live number entity (dew_point_margin_c
    // is not one), which is why it's bound differently than the Safety
    // sliders above.
    const dewSl = this.shadowRoot.querySelector('#dew-point-margin-slider');
    const dewVl = this.shadowRoot.querySelector('#dew-point-margin-val');
    if (dewSl) {
      dewSl.addEventListener('input', e => {
        if (dewVl) dewVl.textContent = `${fn(parseFloat(e.target.value), 1)}°C`;
      });
      dewSl.addEventListener('change', async e => {
        const entryId = (this._data || {}).entry_id;
        if (!this._hass || !entryId) return;
        try {
          await this._hass.callWS({
            type: 'helix_cultivate/update_settings_fields',
            entry_id: entryId,
            fields: { dew_point_margin_c: parseFloat(e.target.value) },
          });
        } catch (err) {
          console.error('Helix Cultivate: dew_point_margin_c save failed', err);
        }
      });
    }

    // Environmental Learning (Part 10) — only present when
    // this._section === 'learning'; querySelector is a safe no-op otherwise.
    const learningToggle = this.shadowRoot.querySelector('#learning-master-toggle');
    if (learningToggle) {
      learningToggle.addEventListener('change', async e => {
        const entryId = (this._data || {}).entry_id;
        if (!this._hass || !entryId) return;
        try {
          await this._hass.callWS({
            type: 'helix_cultivate/update_settings_fields',
            entry_id: entryId,
            fields: { thermal_learning_enabled: e.target.checked },
          });
          if (e.target.checked) this._fetchLearningStatus();
        } catch (err) {
          console.error('Helix Cultivate: thermal_learning_enabled save failed', err);
        }
      });
    }
    const durationSl = this.shadowRoot.querySelector('#learning-duration-slider');
    const durationVl = this.shadowRoot.querySelector('#learning-duration-val');
    if (durationSl) {
      durationSl.addEventListener('input', e => {
        if (durationVl) durationVl.textContent = `${e.target.value}d`;
      });
      durationSl.addEventListener('change', async e => {
        const entryId = (this._data || {}).entry_id;
        if (!this._hass || !entryId) return;
        try {
          await this._hass.callWS({
            type: 'helix_cultivate/update_settings_fields',
            entry_id: entryId,
            fields: { thermal_learning_duration_days: parseInt(e.target.value, 10) },
          });
        } catch (err) {
          console.error('Helix Cultivate: thermal_learning_duration_days save failed', err);
        }
      });
    }
    const exportToggle = this.shadowRoot.querySelector('#learning-export-toggle');
    const exportUrlInput = this.shadowRoot.querySelector('#learning-export-url');
    const saveExportFields = async () => {
      const entryId = (this._data || {}).entry_id;
      if (!this._hass || !entryId) return;
      try {
        await this._hass.callWS({
          type: 'helix_cultivate/update_settings_fields',
          entry_id: entryId,
          fields: {
            thermal_learning_export_enabled: exportToggle ? exportToggle.checked : false,
            thermal_learning_export_url: exportUrlInput ? exportUrlInput.value : '',
          },
        });
      } catch (err) {
        console.error('Helix Cultivate: learning export settings save failed', err);
      }
    };
    if (exportToggle) exportToggle.addEventListener('change', saveExportFields);
    if (exportUrlInput) exportUrlInput.addEventListener('change', saveExportFields);

    this.shadowRoot.querySelectorAll('.learning-start-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!this._hass || btn.disabled) return;
        const zone = btn.dataset.zone;
        const type = btn.dataset.type;
        this._learningActionStatus = 'Starting…';
        this._render();
        try {
          await this._hass.callWS({
            type: type === 'deep_calibration'
              ? 'helix_cultivate/start_deep_calibration'
              : 'helix_cultivate/start_live_actuator_test',
            zone,
          });
          this._learningActionStatus = '✅ Test started';
        } catch (err) {
          this._learningActionStatus = `❌ ${err.message || 'Could not start test'}`;
        }
        await this._fetchLearningStatus();
      });
    });

    // Energy & ROI — gear icon and Reset button (only present when
    // this._section === 'energy'; querySelector is a safe no-op otherwise).
    _bindGearBtn(this.shadowRoot, this);
    const resetBtn = this.shadowRoot.querySelector('#energy-reset-btn');
    const resetStatus = this.shadowRoot.querySelector('#energy-reset-status');
    if (resetBtn) {
      resetBtn.addEventListener('click', async () => {
        if (!this._hass) return;
        resetBtn.disabled = true;
        if (resetStatus) resetStatus.textContent = 'Resetting…';
        try {
          await this._hass.callWS({ type: 'helix_cultivate/reset_energy_cycle' });
          if (resetStatus) resetStatus.textContent = '✅ Reset — archived as Previous Cycle';
          // Reuses the hardware-mapping refresh signal to trigger the root
          // panel's get_config_summary re-fetch — that's what actually
          // updates the cached Previous Cycle figure this tab reads.
          this.dispatchEvent(new CustomEvent('hw-map-saved', { bubbles: true, composed: true }));
        } catch (e) {
          console.error('Helix Cultivate: energy cycle reset failed', e);
          if (resetStatus) resetStatus.textContent = '❌ Reset failed — see console';
        } finally {
          resetBtn.disabled = false;
        }
      });
    }
  }
  connectedCallback() { this._render(); }
}
customElements.define('helix-tab-settings', HelixTabSettings);

// ─────────────────────────────────────────────────────────────────────────────
// Root Panel  <helix-panel>
// ─────────────────────────────────────────────────────────────────────────────

class HelixPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._activeTab = 'telemetry';
    this._theme = localStorage.getItem('helix-theme') || 'dark';
    this._entryId = null;
    this._hwMap = {};
    this._isDryingUnlocked = false;
    this._previousCycleEnergy = null;
  }

  async _fetchConfigSummary() {
    try {
      const result = await this._hass.callWS({ type: 'helix_cultivate/get_config_summary' });
      this._entryId = result.entry_id;
      this._hwMap   = result.hardware || {};
      this._isDryingUnlocked = !!result.is_drying_unlocked;
      this._previousCycleEnergy = result.previous_cycle_energy || null;
      this._update();
    } catch (e) {
      console.warn('Helix Cultivate: could not fetch config summary', e);
    }
  }

  setConfig() {}

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  get hass() { return this._hass; }

  // ── Entity read helpers ────────────────────────────────────────────────────

  _sensorNum(suffix) {
    return _numState(this._hass, `sensor.helix_cultivate_${suffix}`);
  }
  _sensorStr(suffix) {
    return _state(this._hass, `sensor.helix_cultivate_${suffix}`);
  }
  _num(suffix) {
    return _numState(this._hass, `number.helix_cultivate_${suffix}`);
  }
  _sel(suffix) {
    return _state(this._hass, `select.helix_cultivate_${suffix}`);
  }
  _sw(suffix) {
    return _swOn(this._hass, `switch.helix_cultivate_${suffix}`);
  }
  _attr(suffix, domain, attribute) {
    return _attr(this._hass, `${domain}.helix_cultivate_${suffix}`, attribute);
  }

  // ── Build consolidated data object ─────────────────────────────────────────

  _buildData() {
    const h = this._hass;
    if (!h) return {};

    const topology = this._sel('topology') || 'coordinated';

    // Read the enable flags — prefer options/data attributes stored on the exhaust sensor
    // (the coordinator writes them as attributes), fall back to topology heuristic
    const enableCond = this._attr('exhaust_speed', 'sensor', 'enable_conditioning_room');
    const enableDry  = this._attr('exhaust_speed', 'sensor', 'enable_drying_environment');
    const condEnabled = enableCond != null ? Boolean(enableCond) : topology === 'coordinated';
    const dryEnabled  = enableDry  != null ? Boolean(enableDry)  : false;

    // Stage
    const grow_stage_slug = this._sel('grow_stage') || 'germination';
    const stageMeta = STAGE_META[grow_stage_slug] || STAGE_META.germination;
    const cycleComplete = this._attr('grow_stage', 'sensor', 'cycle_complete') || false;
    const stageDurationsPlanned = this._attr('grow_stage', 'sensor', 'stage_durations_planned') || {};

    // Outdoor weather — temp/RH come from the coordinator (which applies the
    // local weather station override, same precedence as a canopy sensor
    // tier, server-side) rather than being re-derived here. Condition is
    // still read directly off the forecast/weather entity's own state.
    // Forecast temperature isn't shown: the `forecast` state attribute this
    // used to read was removed from HA core (see climate_engine.py's
    // _fetch_weather_forecast, which now uses the get_forecasts service for
    // the exhaust feedforward calc — surfacing it here too would need a
    // second, separate service round trip from the frontend).
    const weatherId = this._attr('exhaust_speed', 'sensor', 'outdoor_weather_entity');
    const outdoorTemp = this._attr('exhaust_speed', 'sensor', 'outdoor_temp_c') ?? null;
    const outdoorRH   = this._attr('exhaust_speed', 'sensor', 'outdoor_rh_pct') ?? null;
    const outdoorCond = (weatherId && h.states[weatherId]) ? h.states[weatherId].state : null;
    const outdoorForecast = null;

    return {
      // Topology & modules
      topology,
      enable_conditioning_room:  condEnabled,
      enable_drying_environment: dryEnabled,

      // Stage
      grow_stage_slug,
      stage_label:    stageMeta.label,
      stage_day:      this._sensorNum('stage_day'),
      stage_duration: this._attr('grow_stage', 'sensor', 'stage_duration') ?? 14,
      cycle_complete: cycleComplete,
      stage_durations_planned: stageDurationsPlanned,

      // Setpoints
      vpd_target:          this._num('vpd_target')   ?? 1.0,
      vpd_target_min:      this._attr('leaf_vpd', 'sensor', 'vpd_target_min'),
      vpd_target_max:      this._attr('leaf_vpd', 'sensor', 'vpd_target_max'),
      temp_setpoint:       this._num('temp_setpoint') ?? 24.0,
      light_intensity_pct: this._num('light_intensity') ?? 100,
      sunrise_ramp_min:    this._num('sunrise_ramp_min') ?? 20,

      // Zone 2 — Primary Grow Space
      zone2_name:    this._attr('exhaust_speed', 'sensor', 'zone2_name') || 'Primary Grow Space',
      upper_temp_c:  this._sensorNum('upper_canopy_temp'),
      upper_rh_pct:  this._sensorNum('upper_canopy_rh'),
      mid_temp_c:    this._sensorNum('mid_canopy_temp'),
      mid_rh_pct:    this._sensorNum('mid_canopy_rh'),
      lower_temp_c:  this._sensorNum('lower_canopy_temp'),
      lower_rh_pct:  this._sensorNum('lower_canopy_rh'),
      leaf_vpd:      this._sensorNum('leaf_vpd'),
      exhaust_pct:   this._sensorNum('exhaust_speed'),
      dli_today:     this._sensorNum('dli_today'),
      cycle_cost:    this._sensorStr('cycle_cost'),
      cycle_kwh:     this._sensorNum('cycle_kwh'),

      // Zone 1 — Conditioning Room
      zone1_name:    this._attr('exhaust_speed', 'sensor', 'zone1_name') || 'Conditioning Room',
      lung_temp_c:   this._sensorNum('lung_temp'),
      lung_rh_pct:   this._sensorNum('lung_rh'),
      lung_enthalpy: this._sensorNum('lung_enthalpy'),

      // Drying
      drying_zone_name: this._attr('exhaust_speed', 'sensor', 'drying_zone_name') || 'Drying Room',
      drying_temp_c:    this._attr('exhaust_speed', 'sensor', 'drying_temp_c'),
      drying_rh_pct:    this._attr('exhaust_speed', 'sensor', 'drying_rh_pct'),
      drying_dehumid_on: this._attr('exhaust_speed', 'sensor', 'drying_dehumid_on') || false,
      drying_exhaust_pct: this._attr('exhaust_speed', 'sensor', 'drying_exhaust_pct') ?? 25,
      drying_circ_pct:   this._attr('exhaust_speed', 'sensor', 'drying_circ_pct') ?? 40,
      drying_hvac_mode:  this._attr('exhaust_speed', 'sensor', 'drying_hvac_mode'),

      // Outdoor
      outdoor_temp_c:       outdoorTemp,
      outdoor_rh_pct:       outdoorRH,
      outdoor_condition:    outdoorCond,
      outdoor_temp_forecast: outdoorForecast,

      // Zone appliance states
      zone1_heater_on:      this._attr('exhaust_speed', 'sensor', 'zone1_heater_on')  || false,
      zone1_ac_on:          this._attr('exhaust_speed', 'sensor', 'zone1_ac_on')      || false,
      zone1_humid_on:       this._attr('exhaust_speed', 'sensor', 'zone1_humid_on')   || false,
      zone1_dehumid_on:     this._attr('exhaust_speed', 'sensor', 'zone1_dehumid_on') || false,
      zone1_backup_heater_on: this._attr('exhaust_speed', 'sensor', 'zone1_backup_heater_on') || false,
      zone1_reverse_cycle_mode: this._attr('exhaust_speed', 'sensor', 'zone1_reverse_cycle_mode'),
      zone2_heater_on:      this._attr('exhaust_speed', 'sensor', 'zone2_heater_on')  || false,
      zone2_ac_on:          this._attr('exhaust_speed', 'sensor', 'zone2_ac_on')      || false,
      zone2_humid_on:       this._attr('exhaust_speed', 'sensor', 'zone2_humid_on')   || false,
      zone2_dehumid_on:     this._attr('exhaust_speed', 'sensor', 'zone2_dehumid_on') || false,

      // Fan matrix — count (Part 3.3) reflects the actual number of mapped
      // fan entities (upper_fans/mid_fans/lower_fans, written by the
      // gear-icon Circulation Fan Mapping section), not a hardcoded 0.
      upper_fan_speed:    this._num('upper_fan_speed')    ?? 50,
      upper_fan_variance: this._num('upper_fan_variance') ?? 20,
      breeze_upper_enabled: this._sw('breeze_upper'),
      upper_fan_count: (this._hwMap.upper_fans || []).filter(Boolean).length,
      mid_fan_speed:    this._num('mid_fan_speed')    ?? 50,
      mid_fan_variance: this._num('mid_fan_variance') ?? 20,
      breeze_mid_enabled: this._sw('breeze_mid'),
      mid_fan_count: (this._hwMap.mid_fans || []).filter(Boolean).length,
      lower_fan_speed:    this._num('lower_fan_speed')    ?? 50,
      lower_fan_variance: this._num('lower_fan_variance') ?? 20,
      breeze_lower_enabled: this._sw('breeze_lower'),
      lower_fan_count: (this._hwMap.lower_fans || []).filter(Boolean).length,

      // Switches
      smooth_glides: this._sw('smooth_glides'),
      phase: this._attr('exhaust_speed', 'sensor', 'lights_on') ? 'day' : 'night',
      thermal_runaway: this._attr('exhaust_speed', 'sensor', 'thermal_runaway_active') === true,
      sensor_dropout:  this._attr('upper_canopy_temp', 'sensor', 'sensor_dropout') === true,

      // Progression
      progression_mode: this._sel('progression_mode') || 'manual',

      // Calibration offsets (stored as attributes on exhaust sensor for now)
      primary_temp_offset:     this._attr('exhaust_speed', 'sensor', 'primary_temp_offset')     ?? 0,
      primary_humidity_offset: this._attr('exhaust_speed', 'sensor', 'primary_humidity_offset') ?? 0,
      upper_temp_offset:       this._attr('exhaust_speed', 'sensor', 'upper_temp_offset')       ?? 0,
      upper_humidity_offset:   this._attr('exhaust_speed', 'sensor', 'upper_humidity_offset')   ?? 0,
      mid_temp_offset:         this._attr('exhaust_speed', 'sensor', 'mid_temp_offset')         ?? 0,
      mid_humidity_offset:     this._attr('exhaust_speed', 'sensor', 'mid_humidity_offset')     ?? 0,
      lower_temp_offset:       this._attr('exhaust_speed', 'sensor', 'lower_temp_offset')       ?? 0,
      lower_humidity_offset:   this._attr('exhaust_speed', 'sensor', 'lower_humidity_offset')   ?? 0,
      lung_temp_offset:        this._attr('exhaust_speed', 'sensor', 'lung_temp_offset')        ?? 0,
      lung_humidity_offset:    this._attr('exhaust_speed', 'sensor', 'lung_humidity_offset')    ?? 0,
      drying_temp_offset:      this._attr('exhaust_speed', 'sensor', 'drying_temp_offset')      ?? 0,
      drying_humidity_offset:  this._attr('exhaust_speed', 'sensor', 'drying_humidity_offset')  ?? 0,

      // Safety settings (stored on exhaust sensor attributes)
      safety_high_temp_c:  this._attr('exhaust_speed', 'sensor', 'safety_high_temp_c')  ?? 32,
      safety_low_temp_c:   this._attr('exhaust_speed', 'sensor', 'safety_low_temp_c')   ?? 15,
      safety_high_rh_pct:  this._attr('exhaust_speed', 'sensor', 'safety_high_rh_pct')  ?? 85,
      safety_low_rh_pct:   this._attr('exhaust_speed', 'sensor', 'safety_low_rh_pct')   ?? 30,
      sensor_dropout_min:  this._attr('exhaust_speed', 'sensor', 'sensor_dropout_min')  ?? 30,

      // Zone 2 dimensions
      zone2_width_m:    this._attr('exhaust_speed', 'sensor', 'zone2_width_m')    ?? 1.2,
      zone2_depth_m:    this._attr('exhaust_speed', 'sensor', 'zone2_depth_m')    ?? 1.2,
      zone2_height_m:   this._attr('exhaust_speed', 'sensor', 'zone2_height_m')   ?? 2.0,
      zone2_plant_count: this._attr('exhaust_speed', 'sensor', 'zone2_plant_count') ?? 4,

      // Reverse Cycle Unit toggles (v1.4.0 Part 5.2)
      zone1_is_reverse_cycle: this._attr('exhaust_speed', 'sensor', 'zone1_is_reverse_cycle') === true,
      zone2_is_reverse_cycle: this._attr('exhaust_speed', 'sensor', 'zone2_is_reverse_cycle') === true,
      drying_is_reverse_cycle: this._attr('exhaust_speed', 'sensor', 'drying_is_reverse_cycle') === true,
      // Cross-zone dependency flags (v1.4.0 Part 3.1)
      zone2_depends_on_conditioning: this._attr('exhaust_speed', 'sensor', 'zone2_depends_on_conditioning') !== false,
      drying_depends_on_conditioning: this._attr('exhaust_speed', 'sensor', 'drying_depends_on_conditioning') !== false,
      // Environmental Learning System (v1.4.0 Parts 7-10)
      thermal_learning_enabled: this._attr('exhaust_speed', 'sensor', 'thermal_learning_enabled') === true,
      thermal_learning_duration_days: this._attr('exhaust_speed', 'sensor', 'thermal_learning_duration_days') ?? 18,
      thermal_learning_export_enabled: this._attr('exhaust_speed', 'sensor', 'thermal_learning_export_enabled') === true,
      thermal_learning_export_url: this._attr('exhaust_speed', 'sensor', 'thermal_learning_export_url') ?? '',
      // Zone occupancy (v1.4.0 Part 4)
      zone2_occupied: this._attr('exhaust_speed', 'sensor', 'zone2_occupied') === true,
      drying_occupied: this._attr('exhaust_speed', 'sensor', 'drying_occupied') === true,
      drying_batch_elapsed_days: this._attr('exhaust_speed', 'sensor', 'drying_batch_elapsed_days') ?? null,
      // Temporary Override system (v1.5.0 Part 4)
      override_day_temp_c: this._attr('exhaust_speed', 'sensor', 'override_day_temp_c') ?? null,
      override_night_temp_c: this._attr('exhaust_speed', 'sensor', 'override_night_temp_c') ?? null,
      override_day_vpd: this._attr('exhaust_speed', 'sensor', 'override_day_vpd') ?? null,
      override_night_vpd: this._attr('exhaust_speed', 'sensor', 'override_night_vpd') ?? null,
      override_day_light_pct: this._attr('exhaust_speed', 'sensor', 'override_day_light_pct') ?? null,
      override_night_light_pct: this._attr('exhaust_speed', 'sensor', 'override_night_light_pct') ?? null,

      // Independent canopy sensor/fan layer toggles (mid/lower only — upper
      // is the mandatory primary layer for both, no toggle)
      mid_canopy_sensor_enabled: this._attr('exhaust_speed', 'sensor', 'mid_canopy_sensor_enabled') ?? true,
      lower_canopy_sensor_enabled: this._attr('exhaust_speed', 'sensor', 'lower_canopy_sensor_enabled') ?? true,
      mid_canopy_fan_enabled: this._attr('exhaust_speed', 'sensor', 'mid_canopy_fan_enabled') ?? true,
      lower_canopy_fan_enabled: this._attr('exhaust_speed', 'sensor', 'lower_canopy_fan_enabled') ?? true,
      canopy_temp_spread_c: this._attr('exhaust_speed', 'sensor', 'canopy_temp_spread_c') ?? null,
      canopy_rh_spread_pct: this._attr('exhaust_speed', 'sensor', 'canopy_rh_spread_pct') ?? null,
      canopy_uniformity_insight: this._attr('exhaust_speed', 'sensor', 'canopy_uniformity_insight') ?? null,

      // Outdoor conditions (local weather station override applied server-side)
      outdoor_weather_entity:       this._attr('exhaust_speed', 'sensor', 'outdoor_weather_entity') ?? null,
      local_weather_station_entity: this._attr('exhaust_speed', 'sensor', 'local_weather_station_entity') ?? null,
      outdoor_temp_c_live: this._attr('exhaust_speed', 'sensor', 'outdoor_temp_c') ?? null,
      outdoor_rh_pct_live: this._attr('exhaust_speed', 'sensor', 'outdoor_rh_pct') ?? null,

      // Lighting & DLI engine (Phase 1.5)
      zone2_light_type:  this._attr('exhaust_speed', 'sensor', 'zone2_light_type')  ?? 'led',
      light_applied_pct: this._attr('exhaust_speed', 'sensor', 'light_applied_pct') ?? 0,
      growth_mode:            this._attr('exhaust_speed', 'sensor', 'growth_mode')            ?? 'photoperiod',
      af_light_hours:         this._attr('exhaust_speed', 'sensor', 'af_light_hours')         ?? 18,
      af_lights_on_time:      this._attr('exhaust_speed', 'sensor', 'af_lights_on_time')      ?? '06:00',
      pp_veg_hours:           this._attr('exhaust_speed', 'sensor', 'pp_veg_hours')           ?? 18,
      pp_veg_lights_on_time:  this._attr('exhaust_speed', 'sensor', 'pp_veg_lights_on_time')  ?? '06:00',
      pp_flower_hours:        this._attr('exhaust_speed', 'sensor', 'pp_flower_hours')        ?? 12,
      pp_flower_lights_on_time: this._attr('exhaust_speed', 'sensor', 'pp_flower_lights_on_time') ?? '06:00',
      ramp_enabled: this._attr('exhaust_speed', 'sensor', 'ramp_enabled') ?? true,
      ramp_preset:  this._attr('exhaust_speed', 'sensor', 'ramp_preset')  ?? 'standard',
      light_wattage_w: this._attr('exhaust_speed', 'sensor', 'light_wattage_w') ?? 600,

      // Supplemental Lighting (independent second light)
      supplemental_light_type: this._attr('exhaust_speed', 'sensor', 'supplemental_light_type') ?? 'led',
      supplemental_mode:       this._attr('exhaust_speed', 'sensor', 'supplemental_mode')       ?? 'synced',
      supplemental_target_stages: this._attr('exhaust_speed', 'sensor', 'supplemental_target_stages') ?? [],
      supplemental_on_time:    this._attr('exhaust_speed', 'sensor', 'supplemental_on_time')    ?? '12:00',
      supplemental_duration_hours: this._attr('exhaust_speed', 'sensor', 'supplemental_duration_hours') ?? 2,
      supplemental_applied_pct: this._attr('exhaust_speed', 'sensor', 'supplemental_applied_pct') ?? 0,

      // DLI target alerting
      target_dli_mol:          this._attr('exhaust_speed', 'sensor', 'target_dli_mol')          ?? 0,
      dli_alert_threshold_pct: this._attr('exhaust_speed', 'sensor', 'dli_alert_threshold_pct') ?? 20,

      // Drying-stage airflow strategy (Part 2)
      drying_exhaust_min_pct:     this._attr('exhaust_speed', 'sensor', 'drying_exhaust_min_pct')     ?? 20,
      drying_humidity_ceiling_pct: this._attr('exhaust_speed', 'sensor', 'drying_humidity_ceiling_pct') ?? 68,
      drying_airflow_mode:        this._attr('exhaust_speed', 'sensor', 'drying_airflow_mode')        ?? 'constant',
      drying_cycle_on_min:        this._attr('exhaust_speed', 'sensor', 'drying_cycle_on_min')        ?? 15,
      drying_cycle_off_min:       this._attr('exhaust_speed', 'sensor', 'drying_cycle_off_min')       ?? 15,
      drying_airflow_applied_pct: this._attr('exhaust_speed', 'sensor', 'drying_airflow_applied_pct') ?? 0,
      drying_humidity_override_active: this._attr('exhaust_speed', 'sensor', 'drying_humidity_override_active') ?? false,

      // Energy / tariff
      tariff_mode:          this._attr('exhaust_speed', 'sensor', 'tariff_mode')          ?? 'anytime',
      tariff_anytime_rate:  this._attr('exhaust_speed', 'sensor', 'tariff_anytime_rate')  ?? null,
      tariff_peak_rate:     this._attr('exhaust_speed', 'sensor', 'tariff_peak_rate')     ?? null,
      tariff_shoulder_rate: this._attr('exhaust_speed', 'sensor', 'tariff_shoulder_rate') ?? null,
      tariff_offpeak_rate:  this._attr('exhaust_speed', 'sensor', 'tariff_offpeak_rate')  ?? null,
      tariff_peak_start:     this._attr('exhaust_speed', 'sensor', 'tariff_peak_start')     ?? '07:00',
      tariff_peak_end:       this._attr('exhaust_speed', 'sensor', 'tariff_peak_end')       ?? '21:00',
      tariff_shoulder_start: this._attr('exhaust_speed', 'sensor', 'tariff_shoulder_start') ?? '07:00',
      tariff_shoulder_end:   this._attr('exhaust_speed', 'sensor', 'tariff_shoulder_end')   ?? '10:00',
      harvest_value_per_oz: this._attr('exhaust_speed', 'sensor', 'harvest_value_per_oz') ?? null,
      water_baseline_ec:    this._attr('exhaust_speed', 'sensor', 'water_baseline_ec')    ?? 0.4,

      // EM sensor entity IDs (zone2 = primary grow space)
      em_zone2_s1: this._attr('exhaust_speed', 'sensor', 'em_zone2_s1') ?? null,
      em_zone2_s2: this._attr('exhaust_speed', 'sensor', 'em_zone2_s2') ?? null,
      em_zone2_s3: this._attr('exhaust_speed', 'sensor', 'em_zone2_s3') ?? null,
      em_zone2_s4: this._attr('exhaust_speed', 'sensor', 'em_zone2_s4') ?? null,
      em_zone1_s1: this._attr('exhaust_speed', 'sensor', 'em_zone1_s1') ?? null,
      em_zone1_s2: this._attr('exhaust_speed', 'sensor', 'em_zone1_s2') ?? null,
      em_zone1_s3: this._attr('exhaust_speed', 'sensor', 'em_zone1_s3') ?? null,
      em_zone1_s4: this._attr('exhaust_speed', 'sensor', 'em_zone1_s4') ?? null,
      em_drying_s1: this._attr('exhaust_speed', 'sensor', 'em_drying_s1') ?? null,
      em_drying_s2: this._attr('exhaust_speed', 'sensor', 'em_drying_s2') ?? null,
      em_drying_s3: this._attr('exhaust_speed', 'sensor', 'em_drying_s3') ?? null,
      em_drying_s4: this._attr('exhaust_speed', 'sensor', 'em_drying_s4') ?? null,
      em_global_s1: this._attr('exhaust_speed', 'sensor', 'em_global_s1') ?? null,
      em_global_s2: this._attr('exhaust_speed', 'sensor', 'em_global_s2') ?? null,
      em_global_s3: this._attr('exhaust_speed', 'sensor', 'em_global_s3') ?? null,
      em_global_s4: this._attr('exhaust_speed', 'sensor', 'em_global_s4') ?? null,
      em_zone1_enabled:  this._attr('exhaust_speed', 'sensor', 'em_zone1_enabled')  !== false,
      em_zone2_enabled:  this._attr('exhaust_speed', 'sensor', 'em_zone2_enabled')  !== false,
      em_drying_enabled: this._attr('exhaust_speed', 'sensor', 'em_drying_enabled') !== false,

      // Previous Cycle (2.7) — from get_config_summary, refreshed via the
      // same hw-map-saved event the Reset button dispatches; null until a
      // Reset or harvest close-out has ever happened for this entry.
      previous_cycle_kwh:        this._previousCycleEnergy?.cycle_kwh ?? null,
      previous_cycle_cost_usd:   this._previousCycleEnergy?.cycle_cost_usd ?? null,
      previous_cycle_archived_at: this._previousCycleEnergy?.archived_at ?? null,

      // Cycle lifecycle (Part 1) — "not_started" or "active", drives the
      // dashboard's "No Active Cycle" empty state.
      cycle_state: this._attr('grow_stage', 'sensor', 'cycle_state') ?? 'active',

      // Sensor Dropout badge detail (Part 2.1)
      sensor_dropout_entities: this._attr('upper_canopy_temp', 'sensor', 'sensor_dropout_entities') ?? [],
      // Actuator dropout badge detail/severity (Part 1.2, v1.4.0)
      actuator_dropout_entities: this._attr('upper_canopy_temp', 'sensor', 'actuator_dropout_entities') ?? [],

      // v1.2.8 feature settings, now exposed for editing (Part 3)
      light_high_temp_dim_c: this._attr('exhaust_speed', 'sensor', 'light_high_temp_dim_c') ?? 29.0,
      wind_sweep_enabled:    this._attr('exhaust_speed', 'sensor', 'wind_sweep_enabled')    ?? false,
      dew_point_margin_c:    this._attr('exhaust_speed', 'sensor', 'dew_point_margin_c')    ?? 2.0,
      preheat_lead_min:      this._attr('exhaust_speed', 'sensor', 'preheat_lead_min')      ?? 15,
      stage_warning_lead_days: this._attr('grow_stage', 'sensor', 'stage_warning_lead_days') ?? 3,

      // Zone hardware mapping (gear-icon picker support)
      entry_id: this._entryId,
      hw_map:   this._hwMap,
      is_drying_unlocked: this._isDryingUnlocked,
    };
  }

  // ── Tab definitions ────────────────────────────────────────────────────────

  _buildTabs(data) {
    const condEnabled = data.enable_conditioning_room ?? true;
    const dryEnabled  = data.enable_drying_environment ?? false;

    const tabs = [
      { id: 'telemetry',    label: 'Telemetry',            icon: '📡' },
      { id: 'plant_cycle',  label: 'Plant Cycle',           icon: '🌱' },
      { id: 'grow_space',   label: 'Primary Grow Space',    icon: '🏕' },
    ];
    if (condEnabled) tabs.push({ id: 'conditioning', label: 'Conditioning Room', icon: '🌬' });
    if (dryEnabled)  tabs.push({ id: 'drying',       label: 'Drying (60/60)',    icon: '🍃' });
    tabs.push({ id: 'journal',  label: 'Journal & IPM', icon: '📋' });
    tabs.push({ id: 'settings', label: '⚙️ Settings',   icon: '' });
    return tabs;
  }

  // ── Ensure active tab is valid ─────────────────────────────────────────────

  _validateTab(tabs) {
    if (!tabs.find(t => t.id === this._activeTab)) {
      this._activeTab = 'telemetry';
    }
  }

  // ── Scaffold render (first paint) ──────────────────────────────────────────

  _ensureScaffold() {
    if (!this._eggs) this._eggs = EasterEggEngine;
    if (this.shadowRoot.querySelector('#hx-root')) return;

    this.shadowRoot.innerHTML = `
      <style>
        ${BASE_CSS}
        :host {
          ${this._theme === 'dark' ? THEME_DARK : THEME_LIGHT}
        }
        .panel-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 10px;
          padding: 10px 0 4px;
        }
        .panel-title { font-size: 1.1rem; font-weight: 800; color: var(--hx-text); }
        .theme-btn {
          padding: 5px 10px; font-size: .75rem; font-weight: 600;
          border: 1px solid var(--hx-border); background: var(--hx-surface2);
          color: var(--hx-text2); cursor: pointer; border-radius: 8px;
        }
      </style>
      <div id="hx-root">
        <div class="panel-wrap">
          <div class="panel-header">
            <span class="panel-title">🌿 Helix Cultivate</span>
            <button class="theme-btn" id="theme-toggle">${this._theme === 'dark' ? '☀ Light' : '🌙 Dark'}</button>
          </div>
          <helix-tab-bar id="hx-tab-bar"></helix-tab-bar>
          <div id="hx-tab-content"></div>
        </div>
      </div>`;

    this.shadowRoot.querySelector('#theme-toggle').addEventListener('click', () => {
      if (this._eggs) this._eggs.onThemeToggle(this);
      this._theme = this._theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('helix-theme', this._theme);
      // Re-apply CSS variable block
      const host = this.shadowRoot.querySelector('style');
      if (host) {
        const src = host.textContent;
        const newBlock = this._theme === 'dark' ? THEME_DARK : THEME_LIGHT;
        host.textContent = src.replace(
          /(THEME_DARK|THEME_LIGHT)[^}]*}/,
          newBlock + '}'
        );
      }
      // Easier: just re-render entire scaffold
      this.shadowRoot.innerHTML = '';
      this._ensureScaffold();
      this._update();
    });

    // Listen for module-change events bubbled from settings tab
    this.shadowRoot.addEventListener('module-change', (e) => {
      const { key, value } = e.detail;
      // These would normally trigger an options_flow update via hass.callWS
      // For now we just store in local state so the tabs update immediately
      if (this._localOverrides) {
        this._localOverrides[key] = value;
      } else {
        this._localOverrides = { [key]: value };
      }
      this._update();
    });

    // Listen for hardware-mapping saves bubbled from any zone's gear-icon
    // picker (Growspace/Conditioning/Drying) — _hwMap is only ever populated
    // by _fetchConfigSummary(), so a save elsewhere needs to trigger a
    // re-fetch here rather than leaving it stale until a hard page refresh.
    this.shadowRoot.addEventListener('hw-map-saved', () => {
      this._fetchConfigSummary();
    });

    // Cross-tab navigation for the Telemetry tab's "No Active Cycle" empty
    // state — its Start New Cycle button lives on the Plant Cycle tab, so
    // it bubbles this request up rather than duplicating the form here.
    this.shadowRoot.addEventListener('request-tab-change', (e) => {
      this._activeTab = e.detail.tab;
      this._update();
    });
  }

  // ── Update routing ─────────────────────────────────────────────────────────

  _update() {
    if (!this._hass) return;
    this._ensureScaffold();

    const data = { ...this._buildData(), ...(this._localOverrides || {}) };
    const tabs  = this._buildTabs(data);
    this._validateTab(tabs);

    // Tab bar
    const tabBar = this.shadowRoot.querySelector('#hx-tab-bar');
    if (tabBar) {
      // Apply theme vars to tab bar shadow
      tabBar.style.cssText = Object.entries({
        '--hx-bg': 'var(--hx-bg)',
        '--hx-surface': 'var(--hx-surface)',
        '--hx-surface2': 'var(--hx-surface2)',
        '--hx-border': 'var(--hx-border)',
        '--hx-text': 'var(--hx-text)',
        '--hx-text2': 'var(--hx-text2)',
        '--hx-accent': 'var(--hx-accent)',
      }).map(([k, v]) => `${k}:${v}`).join(';');

      tabBar.tabs   = tabs;
      tabBar.active = this._activeTab;

      // Only bind once
      if (!tabBar._helixBound) {
        tabBar._helixBound = true;
        tabBar.addEventListener('tab-change', (e) => {
          this._activeTab = e.detail.tab;
          this._update();
        });
      }
    }

    // Tab content
    const content = this.shadowRoot.querySelector('#hx-tab-content');
    if (!content) return;

    // Reuse or recreate tab element — keyed on data-tab-id.
    // CRITICAL: do NOT call content.innerHTML = '' unconditionally; doing so
    // destroys helix-tab-settings every 30s tick and resets _section to its
    // constructor default, causing the Settings sub-tab flicker bug.
    const tabMap = {
      telemetry:    'helix-tab-telemetry',
      plant_cycle:  'helix-tab-cycle',
      grow_space:   'helix-tab-growspace',
      conditioning: 'helix-tab-conditioning',
      drying:       'helix-tab-drying',
      journal:      'helix-tab-journal',
      settings:     'helix-tab-settings',
    };

    const tagName = tabMap[this._activeTab];
    if (!tagName) return;

    // Check whether the current child matches the active tab.
    // If the tab has changed (or content is empty), destroy the old element
    // and create the new one; otherwise reuse the existing element in-place.
    let el = content.firstElementChild;
    if (!el || el.getAttribute('data-tab-id') !== this._activeTab) {
      content.innerHTML = '';
      el = document.createElement(tagName);
      el.setAttribute('data-tab-id', this._activeTab);
      content.appendChild(el);
    }

    // Apply theme CSS vars on every tick (non-destructive — just updates style)
    el.style.cssText = `
      --hx-bg:${getComputedStyle(this).getPropertyValue('--hx-bg') || '#0f0f17'};
      --hx-surface:${getComputedStyle(this).getPropertyValue('--hx-surface') || '#1a1a2e'};
      --hx-surface2:${getComputedStyle(this).getPropertyValue('--hx-surface2') || '#16213e'};
      --hx-card:${getComputedStyle(this).getPropertyValue('--hx-card') || '#1e1e2e'};
      --hx-border:${getComputedStyle(this).getPropertyValue('--hx-border') || 'rgba(255,255,255,0.07)'};
      --hx-text:${getComputedStyle(this).getPropertyValue('--hx-text') || '#e2e8f0'};
      --hx-text2:${getComputedStyle(this).getPropertyValue('--hx-text2') || '#8892a4'};
      --hx-accent:${getComputedStyle(this).getPropertyValue('--hx-accent') || '#7c6dfa'};
      --hx-green:${getComputedStyle(this).getPropertyValue('--hx-green') || '#48c78e'};
      --hx-amber:${getComputedStyle(this).getPropertyValue('--hx-amber') || '#ffb700'};
      --hx-red:${getComputedStyle(this).getPropertyValue('--hx-red') || '#ff5252'};
      --hx-blue:${getComputedStyle(this).getPropertyValue('--hx-blue') || '#209cee'};
      --hx-purple:${getComputedStyle(this).getPropertyValue('--hx-purple') || '#a64dff'};
      --hx-shadow:${getComputedStyle(this).getPropertyValue('--hx-shadow') || '0 4px 20px rgba(0,0,0,0.6)'};
    `;

    // Push updated hass + data on every tick (idempotent property setters)
    el.hass = this._hass;
    el.data = data;

    // Journal tab: pass grow-stage and water EC for nitrogen watch
    if (this._activeTab === 'journal') {
      el.stage   = data.grow_stage_slug;
      el.waterEc = data.water_baseline_ec ?? null;
    }

    // Easter egg ticks (run every _update cycle)
    if (this._eggs) {
      this._eggs.checkMay4th(this);
      this._eggs.check420Drop(this);
      this._eggs.checkJuggernaut(this, data);
      const vpdOnTarget = data.leaf_vpd != null
        && Math.abs(data.leaf_vpd - (data.vpd_target ?? 1.0)) < 0.1;
      this._eggs.onVpdTick(vpdOnTarget, this);
      // Phase 12D — track whether a thermal runaway fired at any point this cycle
      if (data.thermal_runaway === true) {
        this._eggs._thermalRunawayThisCycle = true;
      }
    }
  }

  connectedCallback() {
    this._ensureScaffold();
    this._update();
    this._fetchConfigSummary();
  }
}

// ── Apply theme to host before first paint ────────────────────────────────────

const _helixTheme = localStorage.getItem('helix-theme') || 'dark';
const _styleTag = document.createElement('style');
_styleTag.textContent = `helix-panel { ${_helixTheme === 'dark' ? THEME_DARK : THEME_LIGHT} }`;
document.head.appendChild(_styleTag);

customElements.define('helix-panel', HelixPanel);

// ─────────────────────────────────────────────────────────────────────────────
// Moon Phase Calculator — Meeus synodic cycle algorithm (no external deps)
// ─────────────────────────────────────────────────────────────────────────────

const OLD_WORLD_LORE = {
  NEW:      'New Moon — Sow seeds; the earth draws inward.',
  WAXING_C: 'Waxing Crescent — Rising sap; feed your roots.',
  FIRST_Q:  'First Quarter — Tension builds; prune with intention.',
  WAXING_G: 'Waxing Gibbous — Flush nutrients up; leaf growth peaks.',
  FULL:     'Full Moon — Peak resin expression; harvest in flower.',
  WANING_G: 'Waning Gibbous — Distribute energy downward.',
  LAST_Q:   'Last Quarter — Draw toxins out; best time for flushing.',
  WANING_C: 'Waning Crescent — Rest. Prepare for the new cycle.',
};

function moonPhase(date) {
  // Reference new moon: 6 Jan 2000 18:14 UTC
  const REF_NEW_MOON_JD = 2451550.1;
  const SYNODIC = 29.53059;

  // Julian date from date object
  const jd = (date.getTime() / 86400000) + 2440587.5;
  const phase = ((jd - REF_NEW_MOON_JD) % SYNODIC) / SYNODIC;
  const p = phase < 0 ? phase + 1 : phase;

  let icon, key;
  if (p < 0.0625)      { icon = '🌑'; key = 'NEW'; }
  else if (p < 0.25)   { icon = '🌒'; key = 'WAXING_C'; }
  else if (p < 0.3125) { icon = '🌓'; key = 'FIRST_Q'; }
  else if (p < 0.50)   { icon = '🌔'; key = 'WAXING_G'; }
  else if (p < 0.5625) { icon = '🌕'; key = 'FULL'; }
  else if (p < 0.75)   { icon = '🌖'; key = 'WANING_G'; }
  else if (p < 0.8125) { icon = '🌗'; key = 'LAST_Q'; }
  else                 { icon = '🌘'; key = 'WANING_C'; }

  return { phase: p, icon, tooltip: OLD_WORLD_LORE[key] };
}

// ─────────────────────────────────────────────────────────────────────────────
// JournalClient — WebSocket API bridge to HA journal_store backend
// ─────────────────────────────────────────────────────────────────────────────

const JournalClient = {
  async get(hass) {
    try { return await hass.callWS({ type: 'helix_cultivate/journal/get' }); }
    catch(e) { console.warn('Helix Journal: get failed', e); return null; }
  },
  async addEntry(hass, entry) {
    try { return await hass.callWS({ type: 'helix_cultivate/journal/add_entry', entry }); }
    catch(e) { console.warn('Helix Journal: addEntry failed', e); return null; }
  },
  async markMaintenance(hass, key) {
    try { return await hass.callWS({ type: 'helix_cultivate/journal/mark_maintenance', key }); }
    catch(e) { console.warn('Helix Journal: markMaintenance failed', e); return null; }
  },
  async addIpm(hass, event) {
    try { return await hass.callWS({ type: 'helix_cultivate/journal/add_ipm', event }); }
    catch(e) { console.warn('Helix Journal: addIpm failed', e); return null; }
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Easter Egg Engine
// ─────────────────────────────────────────────────────────────────────────────

const SITH_THEME = `
  --hx-bg:#0a0000; --hx-surface:#1a0000; --hx-surface2:#110000;
  --hx-card:#1a0000; --hx-border:rgba(198,40,40,0.3);
  --hx-text:#ff6b6b; --hx-text2:#c62828;
  --hx-accent:#c62828; --hx-green:#c62828; --hx-amber:#c62828;
  --hx-red:#ff1a1a; --hx-blue:#c62828; --hx-purple:#c62828;
  --hx-shadow:0 4px 20px rgba(198,40,40,0.6);
`;

const EasterEggEngine = {
  _toggleCount: 0,
  _lastToggle: 0,
  _sithActive: false,
  _may4thActive: false,
  _vpdSweetTicks: 0,
  _vpdSweetDays: 0,
  _vpdLastTickDate: null,
  _vpdSweetMilestonesShown: new Set(),
  _thermalRunawayThisCycle: false,
  _juggerActive: false,
  _leafDropTimer: null,
  _420lastHour: -1,
  _420lastFridayDay: -1,

  // ── Dark Side: 5× rapid theme toggle ────────────────────────────────────
  onThemeToggle(panelEl) {
    if (this._may4thActive) return false; // May 4th cannot be overridden
    const now = Date.now();
    if (now - this._lastToggle > 3000) this._toggleCount = 0;
    this._lastToggle = now;
    this._toggleCount++;
    if (this._toggleCount >= 5) {
      this._toggleCount = 0;
      if (this._sithActive) {
        this.clearSith(panelEl);
      } else {
        this.applySith(panelEl);
        console.warn('🔴 I find your lack of VPD disturbing.');
      }
      return true;
    }
    return false;
  },

  applySith(panelEl) {
    this._sithActive = true;
    panelEl.style.cssText = SITH_THEME;
    const st = document.querySelector('style[data-helix-theme]') || _styleTag;
    st.textContent = `helix-panel { ${SITH_THEME} }`;
    panelEl.dispatchEvent(new CustomEvent('helix-sith', { detail: { active: true }, bubbles: true }));
  },

  clearSith(panelEl) {
    this._sithActive = false;
    const theme = localStorage.getItem('helix-theme') || 'dark';
    const css = theme === 'dark' ? THEME_DARK : THEME_LIGHT;
    panelEl.style.cssText = css;
    _styleTag.textContent = `helix-panel { ${css} }`;
    panelEl.dispatchEvent(new CustomEvent('helix-sith', { detail: { active: false }, bubbles: true }));
  },

  // ── May the 4th Protocol ──────────────────────────────────────────────────
  checkMay4th(panelEl) {
    const d = new Date();
    if (d.getMonth() === 4 && d.getDate() === 4) {
      if (!this._may4thActive) {
        this._may4thActive = true;
        this.applySith(panelEl);
        console.info('🌌 May the 4th be with you. Sith theme engaged for 24h.');
      }
    } else {
      this._may4thActive = false;
    }
  },

  // ── 4:20 Drop — cannabis leaf particle effect ─────────────────────────────
  check420Drop(panelEl) {
    const now = new Date();
    const h = now.getHours(), m = now.getMinutes();
    const dayOfWeek = now.getDay(); // 5 = Friday
    const month = now.getMonth(), date = now.getDate();

    const isApril20 = (month === 3 && date === 20);
    const isFriday420 = (dayOfWeek === 5 && h === 16 && m === 20);

    if (isApril20 && h !== this._420lastHour) {
      this._420lastHour = h;
      this._startLeafDrop(panelEl);
    } else if (isFriday420 && date !== this._420lastFridayDay) {
      this._420lastFridayDay = date;
      this._startLeafDrop(panelEl);
    }
  },

  _startLeafDrop(panelEl) {
    if (this._leafDropTimer) return; // already running
    const root = panelEl.shadowRoot || panelEl;
    const leaves = [];
    for (let i = 0; i < 20; i++) {
      const d = document.createElement('div');
      d.className = 'hx-leaf';
      d.textContent = '🌿';
      d.style.cssText = `
        position:fixed; top:-60px; left:${Math.random()*100}vw;
        font-size:${24 + Math.random()*16}px;
        animation: hxLeafFall ${4+Math.random()*4}s linear ${Math.random()*3}s forwards;
        pointer-events:none; user-select:none; z-index:9999;
      `;
      document.body.appendChild(d);
      leaves.push(d);
    }

    // Inject keyframes if not already present
    if (!document.getElementById('hx-leaf-style')) {
      const s = document.createElement('style');
      s.id = 'hx-leaf-style';
      s.textContent = `@keyframes hxLeafFall {
        0%   { transform: translateY(0) rotate(0deg); opacity:1; }
        100% { transform: translateY(105vh) rotate(360deg); opacity:0; }
      }`;
      document.head.appendChild(s);
    }

    this._leafDropTimer = setTimeout(() => {
      leaves.forEach(l => l.remove());
      this._leafDropTimer = null;
    }, 60000);
  },

  // ── Nuke Flashbang ────────────────────────────────────────────────────────
  nukeSequence(panelEl) {
    const root = panelEl.shadowRoot || document.body;

    const flash = document.createElement('div');
    flash.style.cssText = `
      position:fixed; inset:0; background:#fff; opacity:0; z-index:10000;
      transition: opacity 0.4s ease-in;
      pointer-events:none;
    `;
    document.body.appendChild(flash);

    requestAnimationFrame(() => {
      flash.style.opacity = '1';
      setTimeout(() => {
        // Insert "INFESTATION CLEARED" text
        const txt = document.createElement('div');
        txt.style.cssText = `
          position:fixed; inset:0; display:flex; align-items:center;
          justify-content:center; z-index:10001; pointer-events:none;
          background:rgba(255,255,255,0.95);
        `;
        txt.innerHTML = `<span style="
          color:#c62828; font-size:3.5em; font-weight:900;
          text-align:center; letter-spacing:0.05em;
          text-transform:uppercase; opacity:0;
          transition: opacity 0.6s ease-in;
          font-family: system-ui, sans-serif;
          text-shadow: 0 0 40px #c62828;
        ">💥 INFESTATION CLEARED 💥</span>`;
        document.body.appendChild(txt);

        requestAnimationFrame(() => {
          txt.firstElementChild.style.opacity = '1';
          setTimeout(() => {
            txt.firstElementChild.style.transition = 'opacity 1s ease-out';
            txt.firstElementChild.style.opacity = '0';
            flash.style.transition = 'opacity 1s ease-out';
            flash.style.opacity = '0';
            setTimeout(() => { flash.remove(); txt.remove(); }, 1100);
          }, 2500);
        });
      }, 700);
    });
  },

  // ── Juggernaut Mode ───────────────────────────────────────────────────────
  checkJuggernaut(panelEl, data) {
    // Juggernaut: exhaust + all 3 fan tiers at 100%
    const allMax = (
      data.exhaustPct >= 100 &&
      data.upperFanSpeed >= 100 &&
      data.midFanSpeed >= 100 &&
      data.lowerFanSpeed >= 100
    );

    if (allMax && !this._juggerActive) {
      this._juggerActive = true;
      this._showJuggernaut(panelEl);
    } else if (!allMax && this._juggerActive) {
      this._juggerActive = false;
      this._hideJuggernaut(panelEl);
    }
  },

  _showJuggernaut(panelEl) {
    if (!document.getElementById('hx-jugg-style')) {
      const s = document.createElement('style');
      s.id = 'hx-jugg-style';
      s.textContent = `
        @keyframes hxShake {
          0%,100% { transform: translateX(0); }
          20%      { transform: translateX(-4px); }
          40%      { transform: translateX(4px); }
          60%      { transform: translateX(-3px); }
          80%      { transform: translateX(3px); }
        }
        .hx-juggernaut-badge {
          position:fixed; top:60px; right:20px; z-index:9998;
          background:#c62828; color:#fff; font-weight:900;
          padding:8px 18px; border-radius:6px; font-size:1em;
          animation: hxShake 0.3s infinite;
          pointer-events:none; letter-spacing:0.05em;
          box-shadow: 0 0 20px #c62828;
        }
      `;
      document.head.appendChild(s);
    }
    const badge = document.createElement('div');
    badge.id = 'hx-juggernaut-badge';
    badge.className = 'hx-juggernaut-badge';
    badge.textContent = '💀 JUGGERNAUT MODE';
    document.body.appendChild(badge);
  },

  _hideJuggernaut(panelEl) {
    const b = document.getElementById('hx-juggernaut-badge');
    if (b) b.remove();
  },

  // ── VPD Sweet Spot haptic + day-streak achievement tracking ──────────────
  onVpdTick(onTarget, panelEl) {
    if (onTarget) {
      this._vpdSweetTicks++;
      if (this._vpdSweetTicks >= 30) { // 30 × 30s = 15 min
        if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
      }
      // Day-streak counter: 2880 ticks × 30s = 24h of continuous on-target VPD
      if (this._vpdSweetTicks >= 2880) {
        this._vpdSweetDays++;
        this._vpdSweetTicks = 0;
        const milestones = [7, 14, 30];
        if (milestones.includes(this._vpdSweetDays) && !this._vpdSweetMilestonesShown.has(this._vpdSweetDays)) {
          this._vpdSweetMilestonesShown.add(this._vpdSweetDays);
          if (panelEl) {
            this._showAchievement(
              panelEl,
              '🌿 VPD Sweet Spot Streak',
              `${this._vpdSweetDays} consecutive days in the VPD target range!`
            );
          }
        }
      }
    } else {
      this._vpdSweetTicks = 0;
      this._vpdSweetDays = 0;
    }
  },

  // ── Generic achievement toast (Phase 12D) ────────────────────────────────
  _showAchievement(panelEl, title, body) {
    if (!document.getElementById('hx-achievement-style')) {
      const s = document.createElement('style');
      s.id = 'hx-achievement-style';
      s.textContent = `
        @keyframes hxAchieveIn {
          0%   { transform: translateY(-20px); opacity: 0; }
          100% { transform: translateY(0);      opacity: 1; }
        }
        .hx-achievement-toast {
          position:fixed; top:70px; left:50%; transform:translateX(-50%);
          z-index:9999; background:var(--hx-card,#1c1f26);
          border:1px solid var(--hx-accent,#3ecf6a);
          color:var(--hx-text,#fff); padding:12px 20px; border-radius:10px;
          font-size:.85rem; box-shadow:0 4px 24px rgba(0,0,0,.4);
          animation: hxAchieveIn .35s ease-out;
          display:flex; flex-direction:column; gap:2px; max-width:320px;
        }
        .hx-achievement-toast .hx-a-title { font-weight:800; font-size:.9rem; }
        .hx-achievement-toast .hx-a-body { color:var(--hx-text2,#9aa4b2); font-size:.75rem; }
      `;
      document.head.appendChild(s);
    }
    const toast = document.createElement('div');
    toast.className = 'hx-achievement-toast';
    toast.innerHTML = `<span class="hx-a-title">${title}</span><span class="hx-a-body">${body}</span>`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 8000);
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// <helix-tab-journal> — Logbook, IPM interventions, Maintenance hub
// ─────────────────────────────────────────────────────────────────────────────

const MAINT_ITEMS = [
  { key: 'ph_low',    label: 'pH 4.0 Calibration',  icon: '⚗️',  days: 30 },
  { key: 'ph_high',   label: 'pH 7.0 Calibration',  icon: '⚗️',  days: 30 },
  { key: 'ec_low',    label: 'EC 1413 Calibration',  icon: '🔬',  days: 30 },
  { key: 'ec_high',   label: 'EC 12880 Calibration', icon: '🔬',  days: 90 },
  { key: 'reservoir', label: '120L Reservoir Clean', icon: '🪣',  days: 7  },
  { key: 'seaweed',   label: 'Seaweed Foliar Spray', icon: '🌿',  days: 14 },
];

const ENTRY_TYPES = ['nutrient', 'ipm', 'maintenance', 'note'];
const NITROGEN_EC_THRESH = 0.1;
const NITROGEN_VEG_STAGES = new Set(['early_veg', 'late_veg']);

class HelixTabJournal extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._subTab = 'logbook';
    this._journal = null;
    this._hass = null;
    this._stage = null;
    this._waterEc = 0.0;
    this._loading = false;
    this._toast = '';
  }

  set hass(h) { this._hass = h; }
  set stage(s) { this._stage = s; }
  set waterEc(v) { this._waterEc = parseFloat(v) || 0.0; }

  async connectedCallback() {
    await this._loadJournal();
    this._render();
  }

  async _loadJournal() {
    if (!this._hass) return;
    this._loading = true;
    const data = await JournalClient.get(this._hass);
    this._journal = data || { entries: [], maintenance: {}, ipm_events: [] };
    this._loading = false;
  }

  _showToast(msg) {
    this._toast = msg;
    this._render();
    setTimeout(() => { this._toast = ''; this._render(); }, 3000);
  }

  async _handleAddEntry(e) {
    e.preventDefault();
    const form = e.target;
    const fd = new FormData(form);
    const entry = {
      type:     fd.get('type') || 'note',
      label:    fd.get('label') || '',
      dose:     fd.get('dose') || '',
      unit:     fd.get('unit') || '',
      volume_l: parseFloat(fd.get('volume_l')) || 0,
      note:     fd.get('note') || '',
    };
    const created = await JournalClient.addEntry(this._hass, entry);
    if (created) {
      this._journal.entries.unshift(created);
      this._showToast('✅ Entry logged');
      form.reset();
    } else {
      this._showToast('❌ Failed to log entry');
    }
    this._render();
  }

  async _handleMarkMaint(key) {
    const updated = await JournalClient.markMaintenance(this._hass, key);
    if (updated) {
      this._journal.maintenance = updated;
      this._showToast('✅ Maintenance recorded');
    } else {
      this._showToast('❌ Failed to save');
    }
    this._render();
  }

  async _handleIpm(type) {
    if (type === 'pyrethrum') {
      // Find the panel root and trigger nuke sequence
      const panel = document.querySelector('helix-panel');
      if (panel && panel._eggs) panel._eggs.nukeSequence(panel);
    }
    const created = await JournalClient.addIpm(this._hass, { type, note: '' });
    if (created) {
      this._journal.ipm_events.unshift(created);
      this._showToast(type === 'pyrethrum' ? '💥 Pyrethrum deployed. INFESTATION CLEARED.' : '✅ IPM logged');
    }
    this._render();
  }

  _maintDaysUntil(key, periodDays) {
    const last = this._journal?.maintenance?.[key];
    if (!last) return 0; // overdue
    const elapsed = (Date.now() / 1000 - last) / 86400;
    return Math.max(0, Math.ceil(periodDays - elapsed));
  }

  _fmtTs(ms) {
    if (!ms) return '—';
    const d = new Date(ms);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  _renderLogbook() {
    const entries = (this._journal?.entries || []).slice(0, 50);
    return `
      <form class="hx-j-form" id="hx-entry-form">
        <div class="hx-j-row">
          <select name="type" class="hx-j-input">
            ${ENTRY_TYPES.map(t => `<option value="${t}">${t.charAt(0).toUpperCase()+t.slice(1)}</option>`).join('')}
          </select>
          <input name="label" placeholder="Label / Nutrient name" class="hx-j-input" required>
        </div>
        <div class="hx-j-row">
          <input name="dose" placeholder="Dose" class="hx-j-input" style="max-width:100px">
          <input name="unit" placeholder="Unit (mL, g…)" class="hx-j-input" style="max-width:100px">
          <input name="volume_l" type="number" step="0.1" placeholder="Vol (L)" class="hx-j-input" style="max-width:90px">
        </div>
        <input name="note" placeholder="Notes…" class="hx-j-input" style="width:100%">
        <button type="submit" class="hx-j-btn hx-j-btn-green">📝 Log Entry</button>
      </form>
      <div class="hx-j-list">
        ${entries.length === 0 ? '<p class="hx-j-empty">No entries yet.</p>' : entries.map(e => `
          <div class="hx-j-entry">
            <span class="hx-j-tag hx-tag-${escapeHtml(e.type)}">${escapeHtml(e.type)}</span>
            <span class="hx-j-label">${escapeHtml(e.label || e.note) || '—'}</span>
            ${e.dose ? `<span class="hx-j-dose">${escapeHtml(e.dose)} ${escapeHtml(e.unit)}</span>` : ''}
            ${e.volume_l ? `<span class="hx-j-vol">${escapeHtml(e.volume_l)}L</span>` : ''}
            <span class="hx-j-ts">${this._fmtTs(e.ts)}</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  _renderIpm() {
    const events = (this._journal?.ipm_events || []).slice(0, 30);
    return `
      <div class="hx-ipm-buttons">
        <button class="hx-j-btn hx-ipm-yellow" data-ipm="yellow_trap">🟡 Yellow Trap Logged</button>
        <button class="hx-j-btn hx-ipm-blue"   data-ipm="blue_trap">🔵 Blue Trap Logged</button>
        <button class="hx-j-btn hx-ipm-green"  data-ipm="neem">🌿 Neem Oil Applied</button>
        <button class="hx-j-btn hx-ipm-nuke"   data-ipm="pyrethrum">
          ☢️ DEPLOY YATES PYRETHRUM (NUKE)
        </button>
      </div>
      <div class="hx-j-list">
        ${events.length === 0 ? '<p class="hx-j-empty">No IPM events recorded.</p>' : events.map(e => `
          <div class="hx-j-entry">
            <span class="hx-j-tag hx-tag-ipm">${escapeHtml(e.type.replace('_',' '))}</span>
            <span class="hx-j-ts">${this._fmtTs(e.ts)}</span>
            ${e.note ? `<span class="hx-j-label">${escapeHtml(e.note)}</span>` : ''}
          </div>
        `).join('')}
      </div>
    `;
  }

  _renderMaintenance() {
    return `
      <div class="hx-maint-grid">
        ${MAINT_ITEMS.map(item => {
          const due = this._maintDaysUntil(item.key, item.days);
          const overdue = due === 0;
          return `
            <div class="hx-maint-tile ${overdue ? 'hx-maint-overdue' : ''}">
              <span class="hx-maint-icon">${item.icon}</span>
              <span class="hx-maint-label">${item.label}</span>
              <span class="hx-maint-due">${overdue ? '⚠️ Due Now' : `${due}d`}</span>
              <button class="hx-j-btn hx-j-btn-sm" data-maint="${item.key}">✓ Done</button>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  _render() {
    const showNitro = (this._waterEc > NITROGEN_EC_THRESH && NITROGEN_VEG_STAGES.has(this._stage));
    const subContent = {
      logbook: this._renderLogbook(),
      ipm: this._renderIpm(),
      maintenance: this._renderMaintenance(),
    };

    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; padding:16px; }
        .hx-j-sub { display:flex; gap:8px; margin-bottom:16px; }
        .hx-j-sub button { padding:8px 16px; border-radius:20px; border:none; cursor:pointer;
          background:var(--hx-surface2,#16213e); color:var(--hx-text,#e2e8f0); font-size:.9em; }
        .hx-j-sub button.active { background:var(--hx-accent,#7c6dfa); color:#fff; }
        .hx-nitro-warn { background:#ffb70022; border:1px solid #ffb700;
          color:#ffb700; padding:10px 14px; border-radius:8px; margin-bottom:14px; font-size:.9em; }
        .hx-j-form { background:var(--hx-card,#1e1e2e); border-radius:10px;
          padding:14px; margin-bottom:14px; display:flex; flex-direction:column; gap:8px; }
        .hx-j-row { display:flex; gap:8px; flex-wrap:wrap; }
        .hx-j-input { background:var(--hx-surface,#1a1a2e); color:var(--hx-text,#e2e8f0);
          border:1px solid var(--hx-border,rgba(255,255,255,.07));
          border-radius:6px; padding:6px 10px; font-size:.85em; flex:1; min-width:80px; }
        .hx-j-btn { padding:8px 18px; border-radius:8px; border:none; cursor:pointer;
          font-weight:700; font-size:.85em; transition:.2s; margin-top:4px; }
        .hx-j-btn-green { background:var(--hx-green,#48c78e); color:#fff; }
        .hx-j-btn-sm { padding:4px 10px; font-size:.8em; background:var(--hx-surface2,#16213e);
          color:var(--hx-text,#e2e8f0); border-radius:6px; border:1px solid var(--hx-border); }
        .hx-j-list { display:flex; flex-direction:column; gap:6px; max-height:400px; overflow-y:auto; }
        .hx-j-entry { display:flex; align-items:center; gap:8px; flex-wrap:wrap;
          background:var(--hx-card,#1e1e2e); padding:8px 12px; border-radius:8px;
          font-size:.85em; border-left:3px solid var(--hx-accent,#7c6dfa); }
        .hx-j-tag { padding:2px 8px; border-radius:10px; font-size:.75em; font-weight:700; }
        .hx-tag-nutrient { background:#209cee22; color:#209cee; }
        .hx-tag-ipm      { background:#ff525222; color:#ff5252; }
        .hx-tag-maintenance { background:#ffb70022; color:#ffb700; }
        .hx-tag-note     { background:#48c78e22; color:#48c78e; }
        .hx-j-ts  { color:var(--hx-text2,#8892a4); font-size:.78em; margin-left:auto; }
        .hx-j-dose,.hx-j-vol { font-size:.82em; color:var(--hx-text2,#8892a4); }
        .hx-j-empty { color:var(--hx-text2,#8892a4); font-style:italic; padding:20px 0; text-align:center; }
        .hx-ipm-buttons { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:16px; }
        .hx-ipm-yellow { background:#ffb700; color:#000; }
        .hx-ipm-blue   { background:#209cee; color:#fff; }
        .hx-ipm-green  { background:#48c78e; color:#fff; }
        .hx-ipm-nuke   { background:#c62828; color:#fff; font-size:1em;
          padding:12px 22px; animation:none; box-shadow:0 0 20px rgba(198,40,40,.4); }
        .hx-ipm-nuke:hover { background:#ff1a1a; box-shadow:0 0 30px rgba(255,26,26,.7); }
        .hx-maint-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:12px; }
        .hx-maint-tile { background:var(--hx-card,#1e1e2e); border-radius:10px;
          padding:14px; display:flex; flex-direction:column; gap:6px; align-items:flex-start;
          border-left:3px solid var(--hx-accent,#7c6dfa); }
        .hx-maint-overdue { border-left-color:#ff5252; }
        .hx-maint-icon  { font-size:1.6em; }
        .hx-maint-label { font-weight:700; font-size:.9em; color:var(--hx-text); }
        .hx-maint-due   { font-size:.85em; color:var(--hx-text2); }
        .hx-maint-overdue .hx-maint-due { color:#ff5252; font-weight:700; }
        .hx-toast { position:fixed; bottom:24px; right:24px; background:var(--hx-card);
          color:var(--hx-text); padding:10px 20px; border-radius:8px; font-size:.9em;
          box-shadow:var(--hx-shadow); z-index:9999;
          border-left:3px solid var(--hx-green); }
      </style>

      ${this._toast ? `<div class="hx-toast">${this._toast}</div>` : ''}
      ${showNitro ? `<div class="hx-nitro-warn">
        ⚠️ <strong>Nitrogen Watch:</strong> Monitor for The Claw.
        Local water EC ${this._waterEc.toFixed(2)} mS/cm detected during vegetative stage.
      </div>` : ''}

      <div class="hx-j-sub">
        <button class="${this._subTab==='logbook'?'active':''}" data-sub="logbook">📝 Logbook</button>
        <button class="${this._subTab==='ipm'?'active':''}"     data-sub="ipm">🐛 IPM</button>
        <button class="${this._subTab==='maintenance'?'active':''}" data-sub="maintenance">🔧 Maintenance</button>
      </div>

      <div id="hx-j-content">${subContent[this._subTab] || ''}</div>
    `;

    // Event listeners
    this.shadowRoot.querySelectorAll('[data-sub]').forEach(btn => {
      btn.addEventListener('click', () => { this._subTab = btn.dataset.sub; this._render(); });
    });
    const form = this.shadowRoot.getElementById('hx-entry-form');
    if (form) form.addEventListener('submit', e => this._handleAddEntry(e));
    this.shadowRoot.querySelectorAll('[data-maint]').forEach(btn => {
      btn.addEventListener('click', () => this._handleMarkMaint(btn.dataset.maint));
    });
    this.shadowRoot.querySelectorAll('[data-ipm]').forEach(btn => {
      btn.addEventListener('click', () => this._handleIpm(btn.dataset.ipm));
    });
  }
}

customElements.define('helix-tab-journal', HelixTabJournal);
