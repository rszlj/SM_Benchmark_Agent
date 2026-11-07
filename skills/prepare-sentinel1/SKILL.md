---
name: prepare-sentinel1
description: Prepare or resume V1 Sentinel-1 50 m physical-overpass acquisitions and annual NetCDF delivery, including VV-only observations. Excludes 10 m output and temporal composites.
---

# Sentinel-1 50 m overpasses

Use source ID `sentinel1` and profile `sentinel1-grd-iw-50m-v1`.
This skill belongs to the full repository checkout; no separate installation is
needed. If invoked directly, recover scope and authorization from the conversation,
read [shared execution rules](../shared/execution.md), and use
[onboarding](../shared/onboarding.md) only if setup is needed.

Read the [workflow guide](../../docs/sentinel1-preparation.md) before planning or execution for
commands, dependencies, checkpoints, validation and evidence. It is the maintained
technical reference; do not copy its algorithms or flags into ad-hoc tools.

## Source decisions

Preserve IW/10 m source eligibility with VV present, both passes, grouping by
platform/absolute orbit/pass and the earliest slice time. Inconsistent relative
orbits in later slices must not split a physical overpass. Keep VV-only scenes;
absent VH remains NaN. Use the exact 50 m linear-power averaging route and
arithmetic mean angle. Retain individual acquisitions in the annual NetCDF.
Explain bounded discovery/download counts and inspect memory before annual
stacking using the guide's estimates. Do not lower resolution, drop acquisitions
or silently truncate an oversized discovery. Resume validated acquisition checkpoints.

## Coordinate and report

Require a reviewed context plan for the same anchor/year. If it is missing, return
to the coordinator to route the context prerequisites; do not recreate them or
silently add a global download. This route supports one anchor/year and absent
station targets. Read other source skills only if they were also selected.

Offline replay and one month with 11 live acquisitions have passed; see
[online evidence](../../docs/sentinel1-online-validation.json). Fresh-environment
and general provider acceptance remain pending; do not generalize this one case.

Return validated source/context/archive paths, the selected profile, measured
gaps and resumable state to the [coordinator](../extend-soil-moisture-benchmark/SKILL.md).
For cross-family requests, return to the coordinator for the
[unified workflow](../../docs/multi-source-preparation.md). Follow shared
delivery/provenance rules; source preparation does not authorize publishing.

For exact dates and the latest one-month online results, use the
[unified acceptance update](../../docs/multi-source-preparation.md#one-month-live-acceptance-2026-11-08).
Retain the source-specific limitations there; one location/month is not general
provider or coding-agent acceptance.
