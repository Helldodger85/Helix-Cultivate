# Helix Cultivate

**A free, open-source Home Assistant integration for precision environmental control in indoor cultivation.**

Helix Cultivate turns Home Assistant into a full climate controller for a grow tent, conditioning room, and drying space — VPD-range control, predictive humidity management, per-stage profiles, and a purpose-built dashboard, all running on hardware you already own.

Built as a free alternative to commercial cultivation controllers, using the sensors, fans, heaters, and humidifiers you map yourself — no proprietary hardware required.

---

## Features

- **Day/night VPD-range control** — a full deadband corridor per growth stage, not just a single point target, so equipment isn't fighting itself trying to hold an exact number.
- **Predictive climate management** — tracks the rate of change of VPD and pre-empts swings a few minutes ahead, rather than reacting only after a threshold is crossed.
- **Full stage lifecycle** — Germination → Seedling → Early Veg → Late Veg → Stretch → Peak Flower → Ripening → Drying, each with its own day/night temperature anchor and VPD range.
- **Locked 60/60 drying profile by default** — a safe, standard cure profile (15.5°C / 60% RH) that stays locked until you explicitly unlock custom targets.
- **Hardware-agnostic setup** — map any Home Assistant entity (sensor, switch, fan, climate) to a role directly from each zone's card via a gear-icon UI. No YAML editing required.
- **Flexible topology** — run a Primary Grow Space alone (Standalone), or coordinate it with a Conditioning Room and dedicated Drying Room (Coordinated).
- **Weather-aware feedforward** — optionally factors outdoor temperature/humidity forecasts into pre-conditioning.
- **Energy & ROI tracking** — live power draw, per-cycle energy cost, and a harvest report with $/g yield efficiency.
- **Recipe sharing** — export your tuned stage profiles as YAML and import someone else's.
- **Diagnostics & Repairs** — built-in HA diagnostics download and proactive Repairs entries for common misconfiguration.
- **Journal & IPM logging** — nutrient entries, pest management events, and maintenance reminders in one place.
- **Custom dashboard** — live VPD gauge, DLI tracker, sparkline history with target-range bands, and a companion glance card for any Lovelace dashboard.

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

## Project status

Actively developed. Expect frequent changes while core features stabilize — back up your Home Assistant configuration before major updates, and check release notes for any required migration steps.

## Disclaimer

This integration controls real physical hardware — heaters, humidifiers, dehumidifiers, and fans. It is provided as-is, without warranty of any kind. Always use appropriate hardware-level safety devices (thermal cutoffs, GFCI/RCD protection, smoke detection) independent of any software control layer; this integration is not a substitute for standard electrical and fire safety practice.

Cultivation of certain plants is regulated or restricted depending on your jurisdiction. You are responsible for ensuring your use of this software complies with applicable local laws.

## Contributing

Issues and pull requests are welcome. Please open an issue to discuss significant changes before submitting a PR.

## License

[MIT](LICENSE) — feel free to adapt this if you'd prefer a different license; MIT is used here as a permissive default.
