---
name: prepare-mod13q1-ndvi
description: Prepare or resume separate Terra MOD13Q1 V1 NDVI. Use for Terra NDVI requests, not Aqua NDVI or a fused Terra/Aqua product.
---

# Terra MOD13Q1 NDVI

Use source ID `mod13q1_ndvi` and profile `mod13q1-ndvi-v1-separate`.
This skill belongs to the full repository checkout; no separate installation is
needed. If invoked directly, recover scope and authorization from the conversation,
read [shared execution rules](../shared/execution.md), and use
[onboarding](../shared/onboarding.md) only if setup is needed.

Read the [workflow guide](../../docs/modis-preparation.md) before planning or execution for
commands, dependencies, checkpoints, validation and evidence. It is the maintained
technical reference; do not copy its algorithms or flags into ad-hoc tools.

## Source decisions

Select `mod13q1_ndvi` only unless other products are requested. Retain Terra's
V1 intermediate EPSG:4326 retrieval grid, 16-day dates and 250 m output grid.
Do not apply Aqua's corrected native-sphere normalized-convolution path to Terra.
Preserve the raw valid range and scaling in the shared guide. Deliver one separate
Terra annual NDVI raster; do not fuse its dates or values with Aqua.

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
