---
name: prepare-myd13q1-ndvi
description: Prepare or resume separate Aqua MYD13Q1 V1 NDVI using the final corrected CRS and mask-weight interpolation. Excludes Terra NDVI and platform fusion.
---

# Aqua MYD13Q1 NDVI

Use source ID `myd13q1_ndvi` and profile `myd13q1-ndvi-v1-separate`.
This skill belongs to the full repository checkout; no separate installation is
needed. If invoked directly, recover scope and authorization from the conversation,
read [shared execution rules](../shared/execution.md), and use
[onboarding](../shared/onboarding.md) only if setup is needed.

Read the [workflow guide](../../docs/modis-preparation.md) before planning or execution for
commands, dependencies, checkpoints, validation and evidence. It is the maintained
technical reference; do not copy its algorithms or flags into ad-hoc tools.

## Source decisions

Select `myd13q1_ndvi` only unless other products are requested. Retain Aqua's
authoritative MODIS sinusoidal sphere and final V1 normalized convolution: bilinear
reprojection of values and validity weights separately, then division above the
recorded weight threshold. The generic Terra kernel is not equivalent. Preserve
Aqua's 16-day date offset and 250 m output; deliver its own annual NDVI raster.

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
