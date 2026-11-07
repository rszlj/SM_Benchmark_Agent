---
name: prepare-mcd12q1
description: Prepare or resume annual V1 MCD12Q1 LC_Type1 land cover for a benchmark anchor. Excludes the historical generic multiband land-cover profile.
---

# MCD12Q1 land cover

Use source ID `mcd12q1` and profile `mcd12q1-v1-igbp-annual`.
This skill belongs to the full repository checkout; no separate installation is
needed. If invoked directly, recover scope and authorization from the conversation,
read [shared execution rules](../shared/execution.md), and use
[onboarding](../shared/onboarding.md) only if setup is needed.

Read the [workflow guide](../../docs/context-preparation.md) before planning or execution for
commands, dependencies, checkpoints, validation and evidence. It is the maintained
technical reference; do not copy its algorithms or flags into ad-hoc tools.

## Source decisions

Select annual LC_Type1 only, with categorical nearest-neighbour reprojection
and the exact 500 m context. Preserve category codes, masks, native CRS and actual
year coverage. Do not substitute the generic multiband land-cover downloader.
Reuse only matching anchor/year checkpoints; static cross-year reuse does not apply.

## Coordinate and report

The current context CLI prepares SRTM, HWSD2 and MCD12Q1 together, not this
source alone. Explain that bundle before execution; load companion source skills
only when their preparation is needed. A missing HWSD2 prerequisite stops the
context workflow before other remote retrieval.

Offline acceptance is recorded in the workflow guide. Live retrieval and fresh-
environment acceptance remain pending; do not describe local replay as online
validation.

Return validated source/context/archive paths, the selected profile, measured
gaps and resumable state to the [coordinator](../extend-soil-moisture-benchmark/SKILL.md).
For cross-family requests, return to the coordinator for the
[unified workflow](../../docs/multi-source-preparation.md). Follow shared
delivery/provenance rules; source preparation does not authorize publishing.
