---
name: prepare-imerg-v07
description: Prepare or resume V1 IMERG V07 half-hourly native-cell observations, including historical missing bands and provider status. Excludes depth aggregation.
---

# IMERG V07 half-hourly

Use source ID `imerg_v07` and profile `imerg-v07-native-half-hourly-v1`.
This skill belongs to the full repository checkout; no separate installation is
needed. If invoked directly, recover scope and authorization from the conversation,
read [shared execution rules](../shared/execution.md), and use
[onboarding](../shared/onboarding.md) only if setup is needed.

Read the [workflow guide](../../docs/timeseries-preparation.md) before planning or execution for
commands, dependencies, checkpoints, validation and evidence. It is the maintained
technical reference; do not copy its algorithms or flags into ad-hoc tools.

## Source decisions

Retain nine fields, native 0.1-degree cell support, half-hour timestamps and
permanent/provisional/unknown status. Precipitation remains a rate in mm h-1,
not half-hour depth. Missing historical bands become null through the established
harmonization; preserve zero and finite negatives. Keep ancillary microwave/IR
null counts separate from precipitation gaps and non-permanent status when
reporting availability. Reuse only validated monthly checkpoints.

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
