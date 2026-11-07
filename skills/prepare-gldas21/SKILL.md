---
name: prepare-gldas21
description: Prepare or resume the V1 four-layer GLDAS-2.1 Noah native-cell series and its station-free annual delivery. Excludes the legacy broad-variable export.
---

# GLDAS-2.1 Noah

Use source ID `gldas21` and profile `gldas21-noah-four-layer-v1`.
This skill belongs to the full repository checkout; no separate installation is
needed. If invoked directly, recover scope and authorization from the conversation,
read [shared execution rules](../shared/execution.md), and use
[onboarding](../shared/onboarding.md) only if setup is needed.

Read the [workflow guide](../../docs/gldas-pilot.md) before planning or execution for
commands, dependencies, checkpoints, validation and evidence. It is the maintained
technical reference; do not copy its algorithms or flags into ad-hoc tools.

## Source decisions

Keep four native soil-moisture layers in kg m-2 at 0.25-degree cell support.
The three-hour samples are instantaneous; interval end is the next slot, not an
averaging interval. Do not convert to volumetric moisture, average depths or
interpolate onto a fine grid. Preserve finite values including zero and negatives;
use null for provider masks/NaN. Validate monthly checkpoints, cadence and gaps.
Use the explicit `--workflow gldas` branch; the default command is catalogue reuse.

## Coordinate and report

Require a reviewed context plan for the same anchor/year. If it is missing, return
to the coordinator to route the context prerequisites; do not recreate them or
silently add a global download. This route supports one anchor/year and absent
station targets. Read other source skills only if they were also selected.

One live GEE cell/year test and offline replay have passed. This does not prove
new-location multi-source or cross-model acceptance.

Return validated source/context/archive paths, the selected profile, measured
gaps and resumable state to the [coordinator](../extend-soil-moisture-benchmark/SKILL.md).
For cross-family requests, return to the coordinator for the
[unified workflow](../../docs/multi-source-preparation.md). Follow shared
delivery/provenance rules; source preparation does not authorize publishing.

For exact dates and the latest one-month online results, use the
[unified acceptance update](../../docs/multi-source-preparation.md#one-month-live-acceptance-2026-11-08).
Retain the source-specific limitations there; one location/month is not general
provider or coding-agent acceptance.
