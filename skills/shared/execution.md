# Shared execution and delivery contract

These rules apply to the coordinator and every source skill. Read once per task;
follow the selected source guide for exact flags, prerequisites and retry bounds.

- Inspect [implementation status](../../docs/implementation.md) and the actual
  adapter before promising support. Use maintained preparation tools, never
  production recovery scripts or newly improvised scientific algorithms.
- Normalize location and period with the existing grid/request code. Preserve exact
  start/end dates for unified preparation; years requests mean full calendar years.
  Exact anchor/context geometry, native-cell support and source-specific masks
  remain explicit. Never repeat native coarse values into fine rasters.
- Preview offline. Explain selected sources, required context additions, station
  targets, resource limits, missing inputs, release ID and output location. Execute
  only within the user's existing authorization with an unchanged reviewed plan ID.
  A new skill is not a new authorization boundary. Scope expansion or scientific
  changes require agreement if not already authorized.
- Preserve product versions, resampling, physical units and target definitions.
  Do not silently change them to get a request working. A registered retrievable
  route does not promise provider coverage. Provider errors are not data absence.
- Validate actual checkpoints before reuse. Keep completed source work on failure;
  obey the selected tool's bounded retries. Authentication, permission and quota
  failures stop without account/project switching. Report sanitized error categories,
  not raw messages that may reveal project or credential details.
- For non-context preparation, require a reviewed context plan for the same
  anchor/year. The current context CLI prepares SRTM/HWSD2/MCD12Q1 together;
  its full scope and HWSD2 prerequisites must be visible. Context preparation
  does not implicitly retrieve other selected sources.
- Inspect written outputs for source identity, spatial alignment, dates, units,
  masks and coverage before packaging. Keep missing observations missing. Explicit
  asset assembly verifies integrity; it does not establish scientific correctness.
- Whole-ZIP reuse preserves all original sources and targets, including unselected
  ones. Explain that behavior. Absent-target requests cannot reuse station-bearing
  ZIPs. New station-free delivery declares ISMN absent by design; do not infer
  station targets from coordinates.
- Preserve V1 as a fixed external data release. Assign distinct release IDs to
  extensions and updates, verify archives after relocation, and report unresolved
  gaps. Never overwrite distributed data silently or publish/push without a request.
- Public provenance records source identities, parameters, code versions and gaps.
  Exclude user project IDs, credentials, private provider logs and absolute local
  paths. Keep caches, local environments, downloads and outputs out of Git.
- Distinguish simulated tests, local replay, online retrieval, new-location tests
  and cross-model trials. Never generalize one successful test to all of these.

Return to the coordinator: source/profile, anchor/year, validated asset/context or
archive path, availability and gaps, resumable state, and the evidence actually
obtained. A failure is reported with retained checkpoints and the next unmet
prerequisite; it must not masquerade as successful delivery.
