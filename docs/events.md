# Helix Cultivate — HA bus events

Helix Cultivate fires these events on the Home Assistant event bus so you can
build your own automations against grow-state changes, independent of the
integration's own notification system (`persistent_notification` / mobile
push via `CONF_NOTIFY_TARGET`).

Every event includes `entry_id` so a multi-instance setup (rare, but
supported) can be filtered in an automation trigger.

## `helix_cultivate_stage_changed`

Fired on every grow-stage transition — automatic timeframe advancement,
a manual override via the stage select entity, an externally-written
`current_stage` config value, and the cycle reset that follows harvest
close-out.

| Field | Type | Description |
|---|---|---|
| `entry_id` | string | Config entry ID |
| `previous_stage` | string | Stage slug the grow just left (e.g. `"late_veg"`) |
| `new_stage` | string | Stage slug the grow just entered (e.g. `"stretch"`) |
| `timestamp` | string | ISO 8601 UTC timestamp |

```yaml
trigger:
  - platform: event
    event_type: helix_cultivate_stage_changed
    event_data:
      new_stage: peak_flower
action:
  - service: notify.mobile_app
    data:
      message: "Entering peak flower — time to check trichomes."
```

## `helix_cultivate_harvest_complete`

Fired once a harvest has been archived to the journal store and the cycle
counters/stage machine are about to reset (this event fires just before the
reset, and is followed by a `helix_cultivate_stage_changed` back to the
first stage in the sequence).

| Field | Type | Description |
|---|---|---|
| `entry_id` | string | Config entry ID |
| `dry_weight_g` | float | Dry weight entered at close-out |
| `cycle_cost_usd` | float | Total energy cost for the completed cycle |
| `dollars_per_gram` | float | `cycle_cost_usd / dry_weight_g` |

## `helix_cultivate_chronic_drift_detected`

Fired when leaf VPD has sat continuously outside
`[vpd_target_min, vpd_target_max]` for more than 4 hours (see
`CHRONIC_VPD_DRIFT_DWELL_MIN` in `const.py`). This is distinct from instant
threshold alerts (thermal runaway, sensor dropout) — it's specifically for
slow drift that never crosses a hard safety threshold on its own. Fires
once per continuous excursion episode; resets as soon as VPD returns
in-range, so a later episode can fire again.

| Field | Type | Description |
|---|---|---|
| `entry_id` | string | Config entry ID |
| `leaf_vpd_kpa` | float | Current leaf VPD reading |
| `vpd_target_min` | float | Lower bound of the active target band |
| `vpd_target_max` | float | Upper bound of the active target band |
| `drift_duration_min` | float | Minutes the excursion has been continuous |

## `helix_cultivate_canopy_uniformity_alert`

Fired when the spread (max − min) of temperature or humidity across active
canopy sensor *layers* (upper, plus mid/lower if their independent sensor
toggle is enabled) exceeds 2°C or 8% RH, sustained for 15 minutes. Only
evaluated with 2 or more active sensor layers — with just upper active
there's nothing to compare against, so the diagnostic is skipped entirely.
Independent of the fan-layer toggles: disabling a tier's fan has no effect
on whether its sensor readings feed this diagnostic.

| Field | Type | Description |
|---|---|---|
| `entry_id` | string | Config entry ID |
| `temp_spread_c` | float | Max − min temperature across active sensor layers |
| `rh_spread_pct` | float | Max − min humidity across active sensor layers |
| `insight` | string | Human-readable summary, e.g. `"12% humidity gradient top-to-bottom — check for an airflow dead zone."` |
| `layers_compared` | int | Number of sensor layers included (2 or 3) |
| `drift_duration_min` | float | Minutes the gradient has been continuously sustained |
