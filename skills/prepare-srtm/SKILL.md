---
name: prepare-srtm
description: Prepare or resume V1 SRTM terrain for a selected benchmark anchor. Use for SRTM context inputs, not arbitrary DEM products.
---

# SRTM terrain

Use source ID `srtm` and profile `srtm-v1-horn-six-band`.
This skill belongs to the full repository checkout; no separate installation is
needed. If invoked directly, recover scope and authorization from the conversation,
read [shared execution rules](../shared/execution.md), and use
[onboarding](../shared/onboarding.md) only if setup is needed.

Read the [workflow guide](../../docs/context-preparation.md) before planning or execution for
commands, dependencies, checkpoints, validation and evidence. It is the maintained
technical reference; do not copy its algorithms or flags into ad-hoc tools.

## Source decisions

Use the V1 SRTM terrain kernel, including the existing Horn derivatives and
50 m context aggregation. Preserve its bands, grid and masks; do not replace it
with a generic elevation export. Static prepared assets can be reused across years
of the same anchor after validation. Raw checkpoints survive failed derivation.
Install compatible native GDAL bindings in addition to the contexts extras.
Report actual geographic coverage rather than substituting another DEM.

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
