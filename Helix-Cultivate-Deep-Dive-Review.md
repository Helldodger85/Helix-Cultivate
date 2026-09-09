# Helix Cultivate — Deep-Dive Review

**Repo:** [github.com/Helldodger85/Helix-Cultivate](https://github.com/Helldodger85/Helix-Cultivate) (default branch `master`, tag `v1.1.0`, MIT license)
**Reviewed:** full clone (44 tracked files, ~14,000 lines) — every Python file in `custom_components/helix_cultivate/`, both frontend JS files, translations, tests, and the author's own `plans/plan.md` refactor blueprint (2,560 lines — used to confirm what's already known/planned vs. genuinely new findings below).

Quick correction on the repo location: it's **`Helldodger85`**, not `Helldodger1985` — the `1985` handle 404s. Also worth noting `manifest.json`'s `documentation`/`issue_tracker` fields still point at a placeholder org (`helix-cultivate/helix_cultivate`) that doesn't exist — see Bug 8.

---

## 1. Bugs

Ranked roughly by real-world impact.

### 1.1 Stored XSS in the Journal / IPM logbook — **highest priority**
`www/helix-panel.js`, `_renderLogbook()` (~L3549-3579) and `_renderIpm()` (~L3581-3602).

The logbook form has free-text `name="label"` and `name="note"` inputs. Whatever a user types is sent via `helix_cultivate/journal/add_entry` / `add_ipm` to `journal_store.py`, persisted, and then rendered back with:

```js
<span class="hx-j-label">${e.label || e.note || '—'}</span>
...
${e.note ? `<span class="hx-j-label">${e.note}</span>` : ''}
```

straight into `this.shadowRoot.innerHTML = ...` — no escaping. Anyone who can open the panel can type `<img src=x onerror=fetch(...)>` (or worse) into "Label / Nutrient name" or "Notes", and it will execute for every future viewer of the Journal tab.

This matters more than a typical single-user hobby XSS because:
- The panel is registered with `require_admin: False` (`__init__.py`), so any non-admin household/HA user can reach it.
- It's also registered with `trust_external_script: True`.
- In a shared HA instance (family members, a Nabu Casa remote-access link handed to someone), a low-trust user's journal entry executes in whoever-next-opens-the-tab's browser session, with access to that user's `hass` object.

**Fix:** escape `e.label`/`e.note` (and any other free-text field rendered this way) before interpolation, or build those nodes with `textContent` instead of template-literal `innerHTML`.

### 1.2 Anti-short-cycle protection for discrete AC/dehumidifier is dead code
`climate_engine.py`, `_control_zone()` (~L1250-1262):

```python
cool_allowed = zone.request_cool(want_cool if effective_discrete_ac_id else False)
if not want_cool and zone.ac_on:
    zone.request_cool(False)
    self._record_compressor_off(f"{zone_label}_ac")
```

`zone.request_cool(...)` on line 1 already sets `zone._ac_on` to the new value. By the time line 2 checks `zone.ac_on`, it's already been updated to match `want_cool` — so when `want_cool` is `False`, `zone.ac_on` is already `False` and the branch can never fire. Same pattern, same bug, for the dehumidifier a few lines below.

It's worse than a simple ordering slip: `ClimateEngine.__init__`'s own docstring says it's "*Instantiated fresh each coordinator update cycle*" — so `ZoneInterlock` (and therefore `zone.ac_on`) has **no memory of the previous tick's actual state at all**, even before the ordering bug. There's no cross-tick "was this on a moment ago" signal being compared against anything.

**Net effect:** `_last_compressor_off[...]` is never populated for `{zone}_ac` / `{zone}_dehumid`, so `_compressor_allowed()` always returns `True`. The user-configurable anti-short-cycle dwell (3–10 min, meant to protect compressors from rapid cycling) **never actually engages for any discrete AC or dehumidifier** — only reverse-cycle heat-pump units get it (their code path, `_control_reverse_cycle`, correctly captures `prev_mode` before mutating state, which is why this one works).

Real consequence: a VPD or temp reading oscillating right on a hysteresis boundary can cycle a window AC or dehumidifier compressor on/off every ~30-second tick indefinitely — a textbook cause of premature compressor failure.

**Fix:** track actual previous on/off state somewhere that survives across ticks (the coordinator, following the same pattern already used for `_dehumid_on_since`/`_humid_on_since`), and compare *before* calling `request_cool`/`request_dehumidify`, not after.

### 1.3 Dual/Triple tariff pricing is configured but has zero effect
The options flow (`async_step_energy`) fully builds out `CONF_TARIFF_MODE` (Anytime/Dual/Triple), peak/shoulder/off-peak `$/kWh` rates, and time-window boundaries. But `coordinator._accumulate_energy()` only ever reads the single legacy flat `CONF_ELECTRICITY_RATE`:

```python
rate = float(self._get(CONF_ELECTRICITY_RATE, 0.282))
```

None of `CONF_TARIFF_MODE`/`CONF_TARIFF_PEAK`/`CONF_TARIFF_SHOULDER`/`CONF_TARIFF_OFFPEAK`/window-boundary constants are referenced anywhere outside `const.py` and `options_flow.py` — confirmed by grepping the whole tree. Anyone who sets up Dual or Triple tariff (very common in NZ/AU) silently gets flat-rate-only cost tracking and a wrong `$/g` on the harvest report.

**Fix:** add a `_current_tariff_rate()` helper in the coordinator that resolves the active window against `dt_util.now()` per the configured mode, and use it in `_accumulate_energy()`.

### 1.4 Drying-zone and Global energy-monitor sensor slots are never read
Same family of bug as 1.3. The options flow lets you map up to 4 energy-monitor sensors each for `CONF_EM_DRYING_SENSORS` and `CONF_EM_GLOBAL_SENSORS`, but `_read_em_watts()` only sums `CONF_EM_ZONE1_SENSORS` and `CONF_EM_ZONE2_SENSORS`:

```python
for list_key in (CONF_EM_ZONE1_SENSORS, CONF_EM_ZONE2_SENSORS):
```

Drying-room and whole-facility power draw is silently excluded from cycle kWh/cost.

**Fix:** include both lists in the iteration.

### 1.5 Duplicate "joke" critical notification on every thermal runaway
`_handle_thermal_runaway()` fires two separate critical notifications back-to-back — the real "Thermal Runaway Alert", then an intentional Easter egg:

```python
await self._coord._notify_critical(
    title="⚠️ Helix Cultivate — Base Under Siege",
    message=f"Warning: Base Under Siege. ...",
    level="critical",
)
```

This is deliberate (`tests/test_climate_engine.py` explicitly asserts `_notify_critical.await_count == 2` and calls it "the Base Under Siege easter-egg notification" in a comment) — but it doubles push/log noise for a genuine safety emergency, and the wording reads like a joke or a security breach rather than a climate alert. Not the message you want a grower to see mid-emergency.

**Suggestion:** fold the flavor text into the one real alert, or gate it behind an opt-in "fun mode" rather than sending it as an independent critical push every time.

### 1.6 No rate-limiting on repeated critical pushes for sustained conditions
`_notify_critical()`'s `persistent_notification.create` is idempotent (fixed `notification_id`), but the mobile-push fan-out (`notify.*`) has no "already sent" guard. Thermal runaway, sensor dropout, and appliance-dropout all re-invoke `_notify_critical()` on **every ~30-second tick** for as long as the condition holds — a 10-minute runaway or a stale sensor can generate dozens of duplicate phone pushes.

The codebase already knows how to do this right — the light-leak watchdog has a proper one-shot `_light_leak_alerted` flag, cleared only when the condition clears. That pattern just isn't applied to the other three alert paths.

**Fix:** reuse the same "alert once, clear on recovery" flag pattern for runaway / sensor-dropout / appliance-dropout.

### 1.7 Fresh, unconfigured install spams "Sensor Alert" and controls nothing
`config_flow.py` deliberately completes onboarding without requiring any hardware mapping (that's deferred to the options flow — reasonable UX). But `coordinator._check_sensor_dropout()` returns `True` whenever `CONF_PRIMARY_TEMP_SENSOR` isn't configured at all — which is exactly the state of a freshly-added integration before the user opens Settings.

Until the options flow is completed, every ~30 seconds the integration will: force exhaust to the safe floor, skip all zone/drying control (see the `if not sensor_dropout and not thermal_runaway:` gate in `climate_engine.run()`), and fire a critical "Sensor Alert" notification + mobile push (compounded by 1.6). A new user could easily read this as "the integration is broken" rather than "I haven't finished setup yet."

**Fix:** distinguish "sensor genuinely dropped out" from "sensor was never configured" — the latter should be a quiet Repairs issue (infrastructure already exists for this — see `_check_repairs_issues`), not a critical alert.

### 1.8 Broken support links in `manifest.json`
```json
"documentation": "https://github.com/helix-cultivate/helix_cultivate",
"issue_tracker": "https://github.com/helix-cultivate/helix_cultivate/issues"
```
That org/repo doesn't exist (404) — leftover placeholder from before the real repo existed. These are exactly the links HA's integration page and HACS surface as "Documentation" / "Report an issue".

**Fix:** point both at `https://github.com/Helldodger85/Helix-Cultivate`.

### 1.9 Grow-camera snapshots are effectively unreachable once taken
`_maybe_trigger_snapshot()` saves the nightly lights-off photo to a hardcoded `/tmp/helix_YYYYMMDD_HHMM.jpg`. Three problems: `/tmp` isn't guaranteed to survive a container/HAOS restart; it isn't web-served, so nothing can display it; and the coordinator only exposes `_last_snapshot_ts` (a timestamp) in its data — the actual file path is never surfaced anywhere, so the dashboard has no way to link to or show the photo it just took. Files also accumulate with no retention limit.

**Fix:** save under a configurable path in `/config/www/` (or use HA's camera/media pathing), expose the latest path via coordinator data, and add basic retention (keep last N).

### 1.10 Compiled bytecode committed to the repo
`git ls-files` shows 18 `__pycache__/*.pyc` files tracked (no `.gitignore` in the repo at all). Minor, but worth a two-minute fix — bloats the repo and can cause confusing stale-bytecode issues for contributors who don't clean their tree.

---

## 2. Improvements / tech debt

- **Test coverage doesn't cover the bugs that matter.** The only test file, `tests/test_climate_engine.py`, covers a handful of `ClimateEngine`'s more self-contained methods (VPD bang-bang, VPD trend, VPD-assist bias, thermal purge ramp, thermal runaway). There is no test anywhere that asserts `_record_compressor_off` fires when a discrete AC/dehumidifier turns off — which would have caught Bug 1.2 directly — and zero coverage for `coordinator.py`, `stage_manager.py`, `options_flow.py`, `config_flow.py`, the `__init__.py` config-entry migration logic, `journal_store.py`, or any frontend code. For ~4,700 lines of Python driving real HVAC hardware, that's a thin net.
- **VPD control only ever looks at the upper canopy sensor.** `leaf_vpd` is computed solely from `upper_canopy_temp`/`upper_canopy_rh`, even though mid/lower canopy sensors are already wired up and read every tick. Right now the 3-tier data is used only for the stratification fan-boost check. A worst-tier (or configurable control-tier) VPD would give more representative control in taller tents, especially lower-canopy zones that tend to run wetter.
- **Deliberate frontend code duplication is a standing maintenance risk.** `helix-glance-card.js`'s own docstring explains it duplicates ~90 lines of helpers (`_state`, `_numState`, `buildSparklineSVG`, etc.) from `helix-panel.js` because Lovelace's custom-card loading has no module system. That's a reasonable call given the constraint, but a bug fixed in one copy (e.g., the sparkline renderer) can silently stay broken in the other. Worth either a tiny shared `<script>` both files load, or a lightweight bundler step (esbuild) at build time so HACS still ships plain JS.
- **Broad `except Exception` around every appliance service call** (`_set_switch`, `_set_fan_pct`, `_set_reverse_cycle`, `_set_light_intensity`, camera snapshot, plus `sensor.py`'s `native_value` and `select.py`'s setter) is fine for resilience against one flaky entity, but a systematic failure (e.g. a service-call signature change after a core HA update) would degrade climate control silently — nothing surfaces it beyond a `_LOGGER.warning`. The appliance-dropout watchdog already has the right pattern (escalate to a notification after sustained failure); consider applying it to repeated *service-call* failures too, not just entity unavailability.
- **Magic numbers in `climate_engine.py`** (`TEMP_DEADBAND_C=0.5`, `VPD_DEADBAND_KPA=0.05`, `SATURATION_DWELL_MIN=8.0`, `VPD_ASSIST_STEP_C=0.3`, the exhaust PID gains) are fine as shipped defaults but aren't user-configurable — someone tuning a fast relay heater vs. a slow mini-split has no lever besides editing source.
- **Confusing cross-zone safety naming.** `_check_zone1_heater_cutoff(canopy_temp)` is a global check keyed on the *Zone 2* upper-canopy reading, while `_control_zone`'s own `enable_heat_cutoff` bang-bang check for Zone 1 is keyed on `lung_temp` instead. This looks intentional (protect the tent even via the intake room's heater) but the naming makes it easy for a future contributor to "fix" it into an actual bug. Worth a clarifying comment.
- **No CI.** No GitHub Actions workflow despite having a `tests/` directory — `pytest` and HACS/`hassfest` validation aren't run automatically, so the existing tests (and HACS compliance) can silently regress unnoticed.
- Only 4 commits and one tag (`v1.1.0`, on the LICENSE-only commit) — no changelog, and no release-based structure yet for HACS/GitHub's usual update flow.

---

## 3. Feature ideas

Grounded in what's already built, roughly in order of "closest to already half-done":

1. **Wire up the tariff engine** (fixes Bug 1.3) and, once live, add a "shift-friendly load" hint — since day/night stage targets are already known ahead of time, flag when a scheduled action (sunrise ramp, a drying-cycle heater run) is about to straddle a peak-rate window.
2. **Multi-tier VPD control** — use the worst-case (or a configurable control tier) across upper/mid/lower canopy instead of upper-only, now that all three are already sensored and polled.
3. **Persistent energy history.** `cycle_kwh`/`cycle_cost` reset to zero on every restart; only the harvest close-out snapshot survives (in the journal). A small `Store`-backed daily ledger, following the same pattern `journal_store.py` already uses, would let the dashboard chart real kWh-per-day across a whole cycle instead of a live "since last restart" number.
4. **Fertigation / EC-pH module.** `NS_FERTIGATION` is already stubbed as an always-present empty namespace, `CONF_WATER_BASELINE_EC` is already collected in the options flow, and the journal logbook already has a "nutrient" entry type in its dropdown. This looks like the natural next module — dosing pump control plus EC/pH bang-bang or PID.
5. **Recipe library / sharing.** Recipe import/export already round-trips cleanly through schema-validated YAML. A simple community recipe browser (even just a curated GitHub folder of YAML files) fits the stated "Open Grow Box for the community" positioning and saves new growers from hand-tuning all 8 stages from scratch.
6. **Plant-profile presets beyond cannabis.** Given the stated goal of "any plants" plus greenhouse/outdoor, some of the current defaults are still cannabis-flavored: the stage sequence itself (germination → seedling → early_veg → late_veg → stretch → peak_flower → ripening → drying), the `mdi:cannabis` icon on the Grow Stage selector, "Harvest Value per Oz", and the 60/60 "cure" drying lock. A selectable plant profile (leafy greens / fruiting vegetable / cannabis / generic) that swaps stage names, icons, and default VPD curves would make the "for any plant" pitch land immediately for a non-cannabis first-time user.
7. **Outdoor/greenhouse irrigation module.** The biggest gap versus the stated ambition. There's already a hook to build on — `CONF_OUTDOOR_WEATHER_ENTITY` drives a feedforward exhaust correction from the weather entity's forecast. Extending that into soil-moisture-driven valve scheduling, rain-skip logic (reusing the same forecast), and frost-protection alerts would be the natural outdoor-mode.
8. **Camera timelapse.** Once snapshot storage is fixed (Bug 1.9), auto-stitch the nightly photos into a timelapse attached to the Harvest Report — fits nicely with the existing achievement/Easter-egg "delight" layer.
9. **Expand the achievement layer.** The `EasterEggEngine` pattern (per the author's own `plans/plan.md`, Phase 12D) is a nice touch worth building on — once the duplicate-notification issue (Bug 1.5) is fixed by moving "Base Under Siege" out of the safety-alert path, there's room for more achievements built on data already tracked: fastest stage transition without a manual override, cleanest harvest ($/g under a threshold), N cycles without an appliance-dropout alert.
10. **CI pipeline** — cheap to add given `tests/` already exists; run `pytest` plus HACS/`hassfest` validation on every push.

---

*Reviewed by reading the full contents of every Python file, both frontend JS files, translations, tests, and the author's own 2,560-line refactor blueprint (`plans/plan.md`) to separate genuinely new findings from already-known/planned work. Line references are against `master` at commit `e9d3ce9`.*
