---
name: prepare-hwsd2
description: Prepare or reuse corrected V1 HWSD2 soil context and its official global cache. Use for soil mapping units and weighted properties; this is not a GEE source.
---

# HWSD2 soil context

Use source ID `hwsd2` and profile `hwsd2-v1-corrected-seven-layer`.
This skill belongs to the full repository checkout; no separate installation is
needed. If invoked directly, recover scope and authorization from the conversation,
read [shared execution rules](../shared/execution.md), and use
[onboarding](../shared/onboarding.md) only if setup is needed.

Read the [workflow guide](../../docs/context-preparation.md) before planning or execution for
commands, dependencies, checkpoints, validation and evidence. It is the maintained
technical reference; do not copy its algorithms or flags into ad-hoc tools.

## Source decisions

HWSD2 requires a validated global raster and SQLite database. Reuse a supplied
cache when possible. If absent, preview `sm-benchmark-context hwsd-global` and
explain the two official global archives, unknown initial size and disk requirements.
A one-point request does not silently authorize this global preparation. Execute
only within the agreed scope; no automatic retry of failed global preparation.
Retain pinned archive hashes, mapping units, component data and seven-layer weighted
properties. Negative missing codes are excluded before weight renormalization.
Preserve no-soil outputs. Native GDAL and the documented database dependencies are
required. Do not prompt for GEE login for HWSD2 itself; companion contexts may need it.

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
