---
name: prepare-smap-l4
description: Prepare or resume SMAP L4 v007 with the historical GEE 13 km sampling route. Does not establish native EASE cell equivalence or ingest new NAS stacks.
---

# SMAP L4 legacy sampling

Use source `smap_l4`, profile `smap-l4-v007-legacy-13km-v1` and the full checkout.
Recover scope and authorization from the conversation. Read
[shared execution rules](../shared/execution.md), and
[onboarding](../shared/onboarding.md) if setup is needed.
Use the maintained [workflow guide](../../docs/smap-preparation.md) for execution,
checkpoint handling and acceptance evidence.

## Scientific decisions

Retain collection 007, 45 float32 fields and the V1 three-hour calendar. The
historical GEE route samples at the anchor centre with scale 13000 and default
geographic projection. Explain that this is not proven equivalent to the original
NAS EASE cell. Never describe coordinate sanity checks as native-grid validation.
Do not silently change to collection 008, another projection, or another scale.

Absent timestamps become null rows, never interpolated values. Report missing
timestamps and all band null counts. Core soil-moisture coverage determines
availability; peat-related ancillary nulls alone do not invalidate a year.
An available series still has the documented spatial-equivalence limitation.
The v007 catalogue is deprecated; query coverage rather than promising recent years.

## Coordinate and report

Require a reviewed context plan for the same anchor/year. Route missing context
preparation through the [coordinator](../extend-soil-moisture-benchmark/SKILL.md).
This workflow accepts one anchor/year and absent station targets. Use the
[unified workflow](../../docs/multi-source-preparation.md) through the coordinator
for cross-family delivery; do not concatenate independently produced ZIPs.

Return validated paths, gaps, profile and resumable state. Distinguish offline
source-table replay from live acquisition and native-cell equivalence testing;
a one-month live run has passed, while native-cell equivalence remains unverified.
No publication is implied.

For exact dates and the latest one-month online results, use the
[unified acceptance update](../../docs/multi-source-preparation.md#one-month-live-acceptance-2026-11-08).
Retain the source-specific limitations there; one location/month is not general
provider or coding-agent acceptance.
