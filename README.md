# Helix Cultivate

**A free, open-source Home Assistant integration for precision environmental control in indoor cultivation.**

Helix Cultivate turns Home Assistant into a full climate controller for a grow tent, conditioning room, and drying space — VPD-range control, predictive humidity management, per-stage profiles, and a purpose-built dashboard, all running on hardware you already own.

Built as a free alternative to commercial cultivation controllers, using the sensors, fans, heaters, and humidifiers you map yourself — no proprietary hardware required.

> **Project status:** actively developed, pre-1.0 software. Features are genuinely functional and covered by an automated test suite, but the project is still finding and fixing real bugs release to release — see [Known Issues / Current Limitations](#known-issues--current-limitations) below before relying on it for anything safety-critical without independent hardware-level protection.

---

## Features

### Climate control
- **Day/night VPD-range control** — a full deadband corridor per growth stage, not just a single point target, so equipment isn't fighting itself trying to hold an exact number.
- **Predictive climate management** — tracks the rate of change of VPD and pre-empts swings a few minutes ahead, rather than reacting only after a threshold is crossed.
- **Dew point / condensation prediction** — forces exhaust to 100% and lung-room heating on when leaf temperature comes within a configurable margin of the calculated dew point, targeting the actual mechanism behind botrytis/powdery mildew risk rather than just a fixed humidity ceiling.
- **Predictive pre-heating** — brings the room up to temperature ahead of a scheduled lights-off transition instead of reacting after the drop has already started.
- **Multiple independent canopy sensor tiers** — Upper canopy is mandatory; Mid and Lower are independently toggleable, so a single-tier tent and a fully-instrumented multi-tier canopy are both first-class configurations.

### Circulation
- **Multi-fan-per-tier circulation mapping** — map up to 4 fan entities to each canopy tier (Upper/Mid/Lower) from the gear-icon hardware form; every mapped fan in a tier is driven to the same computed speed simultaneously.
- **Breeze mode** — genuinely time-varying speed modulation per tier, cycling a configurable ± variance around the tier's base speed on an async interval, independently enabled/persisted per tier.
- **Canopy wind sweep** — rotates a boosted speed among currently-enabled circulation tiers on a dwell timer instead of running them all at a static speed, mimicking natural gusting wind to reduce microclimates and add stem-strengthening stress. Automatically suspends a tier's own Breeze cycling while wind sweep is actively boosting that tier, then resumes it once released. Growing stages only — never active during Drying.
- **High/low fan-control resolution modes** — continuous percentage, 10-step PWM, or bang-bang, selectable per install.

### Lighting
- **Growth Mode scheduling** — Photoperiod (Veg/Flower hour + lights-on-time pairs) or Autoflower (fixed daily hours), with an optional sunrise/sunset dimming ramp. A single, unified value: surfaced on both the Plant Cycle and Primary Grow Space tabs, changing it from either place updates the same setting everywhere, and it locks read-only the moment a cycle occupies Primary Grow Space (mid-cycle changes would abruptly change the active schedule). Every stage's Profile Card shows a live, read-only reflection of the real computed lighting-hours value for that stage — never an independent, potentially-contradictory number of its own.
- **DLI (Daily Light Integral) engine** — tracks accumulated light per day against a target, with configurable alert thresholds and a photoperiod-extension option.
- **High-temperature graduated light dimming** — throttles light intensity as a soft step strictly below the hard thermal-runaway cutoff, rather than only having a single all-or-nothing cutoff.
- **Supplemental Lighting** — a second, independent light (UV, far-red, or other targeted spectra) with its own fixture type and either Synced (follows Main Lighting) or Targeted (specific stages, its own schedule) mode.

### HVAC
- **Reverse Cycle AirCon support** — when a mapped AirCon entity actually reports supporting `heat_cool`/`auto` mode, it's driven via real thermostat control (`climate.set_hvac_mode` + `climate.set_temperature`), letting the unit's own onboard thermostat regulate continuously. Falls back to discrete heat/cool/off switching for entities that don't report support — never assumed either way. All heat/cool decisions are driven exclusively by each zone's own dedicated sensor entity, never by an actuator's own onboard temperature/humidity reading.
- **`midea_ac.follow_me` support** — for an ESPHome `platform: midea` Reverse Cycle unit, its zone's dedicated sensor reading is separately fed to the unit's own onboard regulation via `follow_me`, correcting for the fact that `follow_me` doesn't change what the entity itself reports back — Helix Cultivate still never reads that entity's own temperature for its own decisions, either way. Best-effort, silently inert on hardware that doesn't support it.
- **Independent Backup Heater staging** — available alongside a Reverse Cycle unit in the same zone (never a substitute for it), engaging only after the primary heat source has been continuously falling behind setpoint (per its zone's dedicated sensor) for a sustained dwell period, with an optional outdoor-temperature confirming floor.

### Safety
- **Configurable safety interlocks** — high/low temperature cutoffs, high/low humidity cutoffs, and a sensor-dropout failsafe timeout, each exposed as both an initial Options Flow field and a live, ongoing-tunable number entity.
- **Thermal runaway / heater over-temp cutoffs** — hard "always wins" overrides that take priority over normal setpoint control.
- **Sensor dropout detection** — falls back to a safe exhaust floor and suspends VPD control if the primary sensor goes stale beyond its configured timeout, with a Home Assistant Repairs entry surfaced for visibility, and escalates the dashboard badge to red specifically when it's an actuator (not just a sensor) that's gone unreachable.
- **Anti-short-cycle protection** — a minimum dwell timer between compressor on/off transitions.
- **Explicit, confirmed cross-zone dependency flags** — whether a grow space or Drying Room depends on Conditioning Room for its own baseline climate is a real, always-visible toggle (defaulting to the conservative "depends"), gating whether Conditioning Room is ever allowed to destabilize its own output for calibration testing while a dependent zone is occupied.

### Drying
- **Locked 60/60 drying profile by default** (15.5°C / 60% RH) — a safe, standard cure profile that stays locked until you explicitly unlock custom day/night targets.
- **Selectable drying airflow strategy** — constant, gentle-cyclic (on/off dwell timers), or a dedicated minimum floor — with an explicit humidity-ceiling override that takes priority over whichever mode is active.

### Cycle & stage management
- **Full stage lifecycle** — Germination → Seedling → Early Veg → Late Veg → Stretch → Peak Flower → Ripening → Drying, each with its own day/night temperature anchor, VPD range, and genuinely editable day-count (with mode-aware recommended-range guidance) — the same value that actually drives `PROG_TIMEFRAME` auto-advance timing and the stage-progression heads-up warning, not a disconnected display number. Permanent saves via "Save Stage Targets" take effect on the very next control-loop tick, even for the stage currently active.
- **Temporary Override** — on Primary Grow Space, a Day/Night-aware set of sliders (Temp Setpoint, VPD Target, Light Intensity) for nudging today's targets without touching your saved stage settings; clearly indicated whenever active, persists across a Day/Night Smooth-Glides flip within the same stage, and automatically clears the moment the stage actually changes.
- **Explicit cycle lifecycle** — a cycle is either not-started or active; starting one and closing out a harvest are deliberate actions rather than an always-on implicit state.
- **Independent zone occupancy** — separate from cycle tracking: with a dedicated Drying Room, "Harvest — Space Now Empty" transfers occupancy from the grow space to the Drying Room (without resetting that batch's own stage tracking or data) so a fresh cycle can start in the freed space while the previous batch finishes curing and closes out its own Harvest Complete independently — two cycles genuinely running at once. The transferred batch's day-count in Drying keeps computing live from its own unchanging start date, exactly like every other stage, rather than freezing at the moment of transfer.
- **Stage-progression heads-up warnings** — flags when a stage is running unusually long against its planned duration.
- **Recipe sharing** — export your tuned stage profiles as YAML and import someone else's.

### Environmental Learning (opt-in)
- **Confidence-weighted learning from real conditions** — off by default; when enabled, fits a genuine multi-variable regression (external weather, time-of-day, season, lighting, and an approximate occupied-hours schedule, combined together rather than requiring an exact combination to repeat) against actuator behavior, refit continuously as new data arrives. A fixed-duration Learning phase graduates unconditionally to an Active phase that never stops refitting — its influence on future predictive feedforward is always blended in proportion to the fitted model's own prediction-interval confidence for the current conditions, never a hard replacement of the generic default, and never confidently wrong on too little data.
- **Deep Calibration & Live Actuator Response Testing** — Deep Calibration deliberately cuts a zone's actuator control for a bounded window to measure free thermal decay (only when that zone, and anything depending on it, is unoccupied); Live Actuator Response Testing nudges a setpoint or steps an actuator through its range to measure response, available regardless of occupancy, and now runs autonomously on a sensible per-zone schedule as well as on manual demand. Both durably survive a restart mid-test.
- **Self-contained storage, optional export** — the same lightweight, no-external-database storage pattern used elsewhere in this integration, with an optional, off-by-default, best-effort InfluxDB/VictoriaMetrics line-protocol export for building your own Grafana dashboards on top.

### Energy & monitoring
- **Energy & ROI tracking** — live power draw, per-cycle energy cost against a configurable tariff (anytime/peak-shoulder-offpeak), and a harvest report with $/g yield efficiency, with a previous-cycle archive.
- **Per-zone energy monitoring slots** — up to 4 wattage-sensor slots each for the Primary Grow Space, Conditioning Room, Drying Room, and a global/whole-system total.
- **Weather-aware feedforward** — optionally factors outdoor temperature/humidity (local weather station override or a mapped weather entity forecast) into pre-conditioning.

### Platform & UX
- **Hardware-agnostic setup** — map any Home Assistant entity (sensor, switch, fan, climate) to a role directly from each zone's card via a gear-icon UI. No YAML editing required.
- **Flexible topology** — run a Primary Grow Space alone (Standalone), or coordinate it with a Conditioning Room and dedicated Drying Room (Coordinated).
- **Custom dashboard** — live VPD gauge, DLI tracker, sparkline history with target-range bands, a circulation fan matrix, and a companion glance card for any Lovelace dashboard.
- **Diagnostics & Repairs** — built-in HA diagnostics download and proactive Repairs entries for common misconfiguration (e.g. sensor dropout).
- **Journal & IPM logging** — nutrient entries, pest management events, and maintenance reminders in one place.

## Installation

### Via HACS (custom repository)

This isn't in the default HACS store yet, so add it manually:

1. HACS → Integrations → ⋮ (top right) → **Custom repositories**
2. Add this repository's URL, category: **Integration**
3. Find **Helix Cultivate** in HACS and install it
4. Restart Home Assistant
5. Settings → Devices & Services → **Add Integration** → search "Helix Cultivate"

### Manual install

Copy the `custom_components/helix_cultivate` folder into your Home Assistant `config/custom_components/` directory, then restart Home Assistant and add the integration as above.

## Getting started

Initial setup is a fast two-step wizard: choose your **topology** (Coordinated or Standalone) and name your zones. That's it — you're up and running immediately.

All hardware mapping happens afterward, per zone, using the **⚙ gear icon** on each zone's card in the dashboard panel. Assign sensors, fans, and appliances one zone at a time, so it's always clear which device belongs to which physical space.

## Requirements

- Home Assistant (see `manifest.json` for the minimum supported version)
- At minimum: one temperature and one humidity sensor for your primary grow space
- Everything else — fans, heaters, humidifiers, dehumidifiers, cameras, weather integration — is optional and can be added incrementally

## Known Issues / Current Limitations

This is actively-developed, pre-1.0 software. Real bugs — including at least one safety-relevant persistence issue and a systemic entity-addressing bug affecting several live dashboard controls — have been found and fixed across recent releases through direct, ongoing auditing, not because the codebase has reached a settled, fully-verified state. Treat every control on the dashboard as something to verify actually took effect (drag a slider, reload, confirm) rather than assumed-correct, especially after an update.

Known, honestly-scoped caveats as of this release:

- Frontend (dashboard panel) behavior — layout, dynamic hardware-mapping forms, and live control wiring — is verified through code review and syntax checking rather than an automated browser test suite; the automated test suite (`tests/`, run via `pytest`) covers backend logic only (coordinator, climate engine, config migrations, entity platforms).
- The Breeze engine's random re-modulation interval (roughly 8-25 seconds) is on the shorter end of what feels like natural gusting for some fan hardware; there's no UI to tune this interval yet.
- Environmental Learning's confidence-weighted model is now a genuine fitted multi-variable regression (numpy-based OLS with prediction-interval confidence), but its output isn't yet wired into any live setpoint decision — the model fits and predicts correctly, nothing in the control loop consults it yet.
- A dedicated Drying Room's own Reverse Cycle unit always uses discrete heat/cool/off switching, regardless of what `hvac_modes` it actually reports — unlike Conditioning Room and Primary Grow Space, it hasn't yet been upgraded to real thermostat-mode control.
- `midea_ac.follow_me` wiring (for ESPHome `platform: midea` Reverse Cycle units) is best-effort and silently no-ops on hardware that doesn't support it; whether your specific device additionally needs an IR transmitter component alongside UART for it to take effect is a question for your own ESPHome configuration, not something this integration can verify.

Current and historical issues are tracked on [GitHub Issues](https://github.com/helix-cultivate/helix_cultivate/issues) — that's the authoritative list, not a static snapshot here that would inevitably go stale.

## Disclaimer

This integration controls real physical hardware — heaters, humidifiers, dehumidifiers, and fans. It is provided as-is, without warranty of any kind. Always use appropriate hardware-level safety devices (thermal cutoffs, GFCI/RCD protection, smoke detection) independent of any software control layer; this integration is not a substitute for standard electrical and fire safety practice.

Cultivation of certain plants is regulated or restricted depending on your jurisdiction. You are responsible for ensuring your use of this software complies with applicable local laws.

## Contributing

Issues and pull requests are welcome. Please open an issue to discuss significant changes before submitting a PR.

## License

[MIT] — This was Vibe Coded specifically for open source alternatives to commercial software or free tier software with paywalls for expanability.
