---
name: extend-soil-moisture-benchmark
description: Guide beginners and coordinate soil-moisture benchmark requests across source skills, offline catalogue reuse, bounded preparation and annual delivery. Use as the repository entry point; source-specific science belongs to the selected source skill.
---

# Coordinate a benchmark extension

This is the entry point for the full repository checkout. Resolve links relative
to their containing file and run commands from the repository root. Read
[implementation status](../../docs/implementation.md) before promising capabilities.
The user talks to this coordinator; do not ask them to choose or install skills.

## Start and route

1. For first use, missing dependencies or provider setup, read
   [onboarding](../shared/onboarding.md). Handle local technical steps for the user.
2. Recover location/extent, time period, requested sources and station-target mode
   from the conversation. Preserve exact requested dates when using unified
   preparation; `years` means full years. Split cross-year date requests at year
   boundaries, with a matching context plan for each segment. Use existing grid
   tools for EASE2 anchors. Ask only for information needed for the next step.
3. Read [execution and delivery rules](../shared/execution.md). Use
   `sm-benchmark-agent` for offline catalogue planning or compatible local reuse.
   A catalogue match alone does not make the archive locally available.
4. Only when preparation is needed, look up requested source IDs in
   [the source index](../source-index.json). Paths in that index are repository-root
   relative. Read only the selected source skills and their relevant guides.
   Read prerequisite skills if those inputs need preparation; a reviewed matching
   context plan can be reused without reloading or redoing every source workflow.
5. Group selected sources by the index's workflow. Its scope describes what the
   actual command accepts. The context CLI prepares a three-source bundle: explain
   additions if the user asked for only one context source. Do not silently expand
   authorization. For sources spanning families, use the index's integrated workflow
   and read the [unified preparation guide](../../docs/multi-source-preparation.md).
6. Present a concrete bounded plan and execute within existing authorization using
   its unchanged plan ID. Return validated outputs, source gaps and acceptance
   limits in the user's language. Reuse checkpoints on later sessions.

## Current boundaries

Each preparation CLI currently supports one anchor/year and absent station targets.
The context workflow returns a context plan; other workflows assemble separate
annual packages using matching contexts. The unified preparation command calls
selected adapters and assembles one package across families. Do not run separate
family commands against the same ZIP or manually concatenate packages. Automatic
multi-anchor/year scheduling remains pending. One-month live acceptance is
recorded in the unified guide, including partial and unavailable sources.

Unimplemented sources are listed explicitly in the index. Their catalogue entries
may support existing V1 reuse, but do not imply retrieval or station ingestion.
Do not generate new scientific processing code to fill a missing adapter.
Do not silently omit a requested source or fabricate station observations.

The source skills delegate to maintained tools; they do not require separate agents
or additional installations. Shared guidance is read once per task. See
[maintenance rules](../../docs/skill-layout.md) when changing this architecture.
