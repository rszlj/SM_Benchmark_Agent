---
name: prepare-era5-land
description: Prepare or resume the V1 raw18 NAS-compatible ERA5-Land hourly native-cell series. Excludes hourly-increment profiles and new CDS/NAS ingestion.
---

# ERA5-Land raw hourly

Use source ID `era5_land` and profile `benchmark-raw18-nas-compatible-v1`.
This skill belongs to the full repository checkout; no separate installation is
needed. If invoked directly, recover scope and authorization from the conversation,
read [shared execution rules](../shared/execution.md), and use
[onboarding](../shared/onboarding.md) only if setup is needed.

Read the [workflow guide](../../docs/timeseries-preparation.md) before planning or execution for
commands, dependencies, checkpoints, validation and evidence. It is the maintained
technical reference; do not copy its algorithms or flags into ad-hoc tools.

## Source decisions

Retain the 18 raw fields, NAS-compatible variable names and float32 table.
Forecast accumulations are not GEE hourly increments: do not deaccumulate,
aggregate or silently substitute `_hourly` bands. Use the existing ERA5 native
cell, not the IMERG grid origin. Validate monthly checkpoints and all variable
null counts. Report partial measured coverage even when an old V1 manifest says
available. Existing finite values and missing timestamps must remain unchanged.

## Coordinate and report

Require a reviewed context plan for the same anchor/year. If it is missing, return
to the coordinator to route the context prerequisites; do not recreate them or
silently add a global download. This route supports one anchor/year and absent
station targets. Read other source skills only if they were also selected.

Offline replay and a one-month live run are recorded in the guides. Fresh-
environment acceptance remains pending; distinguish these evidence types.

Return validated source/context/archive paths, the selected profile, measured
gaps and resumable state to the [coordinator](../extend-soil-moisture-benchmark/SKILL.md).
For cross-family requests, return to the coordinator for the
[unified workflow](../../docs/multi-source-preparation.md). Follow shared
delivery/provenance rules; source preparation does not authorize publishing.

For exact dates and the latest one-month online results, use the
[unified acceptance update](../../docs/multi-source-preparation.md#one-month-live-acceptance-2026-11-08).
Retain the source-specific limitations there; one location/month is not general
provider or coding-agent acceptance.
