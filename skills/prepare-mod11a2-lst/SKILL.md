---
name: prepare-mod11a2-lst
description: Prepare or resume separate Terra MOD11A2 V1 day and night LST. Excludes Aqua LST and combined-platform LST products.
---

# Terra MOD11A2 LST

Use source ID `mod11a2_lst` and profile `mod11a2-lst-v1-separate`.
This skill belongs to the full repository checkout; no separate installation is
needed. If invoked directly, recover scope and authorization from the conversation,
read [shared execution rules](../shared/execution.md), and use
[onboarding](../shared/onboarding.md) only if setup is needed.

Read the [workflow guide](../../docs/modis-preparation.md) before planning or execution for
commands, dependencies, checkpoints, validation and evidence. It is the maintained
technical reference; do not copy its algorithms or flags into ad-hoc tools.

## Source decisions

Select `mod11a2_lst` only unless other products are requested. Retain paired
Terra day/night raw bands, 8-day dates, authoritative MODIS sphere and bilinear
1 km context reprojection. Apply the V1 valid range, 0.02 K scaling and subtraction
of 273.15 exactly as documented. Deliver separate Terra day and night rasters.
Do not add QC filtering, temporal filling or platform fusion.

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
