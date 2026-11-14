# SMAP L3 preparation and extension

Source `smap_l3` uses NSIDC SPL3SMP_E Version 006, collection
`C2938664763-NSIDC_CPRD`, from 31 March 2015. This differs from GEE SMAP L4.
The current route supports completed calendar years only.

## Earthdata setup

Install `.[smap_l3]` in the selected project environment. Use an existing or new
[NASA Earthdata Login](https://urs.earthdata.nasa.gov/). Provider authorization
and terms remain user actions. Credentials belong in the user's home `.netrc`,
not chat, request JSON or Git. It needs a `machine urs.earthdata.nasa.gov` entry
with `login` and `password`. Guide the user to enter these locally. On POSIX use
owner-only permissions (600); on Windows restrict the file's access permissions.
Never print or package this file.

`sm-benchmark-earthdata-check` checks local configuration without networking.
Add `--online` for authorized authentication verification without a data job.
GEE continues to use `credential_ref` in mixed requests; the L3 adapter ignores
that field and uses home `.netrc`. Missing Earthdata login does not block other
sources or verified local reuse.

## Unified delivery

Add `smap_l3` to the same request's sources, alongside `era5_land` or other
registered inputs. Use the existing command, matching context plan and union
of selected dependency extras:

```text
sm-benchmark-prepare --request configs/smap-l3-request.example.json --context-plan cache/context-plan.json --asset-root cache/sources
```

Preview is offline. Execute with `--execute --accept-plan PLAN_ID` after scope
review. Exact dates apply to all adapters, so an April request does not silently
retrieve a full year of L3. The orchestrator prepares adapters serially and writes
one ZIP after validation. No manual SMAP postprocessing is needed. Resume from
source checkpoints; replan when code changes. One anchor/year and absent station
targets remain the current unified preparation limits.

## Scientific profile

AM/PM records retain soil moisture/error, corrected and uncorrected H/V TB,
retrieval/surface/TB flags, native row/column, coordinates, source time and UTC
observation time. Select the native EASE2 cell at the anchor center without
interpolation. Subset coordinates must match within one metre and non-null
row/column values must agree. Uncorrected TB retains 36 km native support despite
9 km posting. Source TDB seconds are converted to UTC with leap seconds, not a
fixed UTC epoch addition. Units are m3/m3 for soil moisture and K for TB.

Provider fill attributes/nonfinite values become null, preserving valid zeros
and flag codes. No additional quality screening is imposed. Missing granule
dates and null counts for every field remain explicit. Availability in the
unified route reflects the requested dates and non-null soil moisture, not an
assumption that a daily granule has valid retrievals at every cell. No imputation
or interpolation occurs.

## Checkpoints and limits

Harmony work is monthly and serial with saved job IDs. Uncertain submissions,
failed/canceled/paused jobs and authentication failures stop for review; they
are not automatically resubmitted or treated as scientific absence. The unified
adapter polls at most 180 times, waiting 30 seconds for running jobs, then stops
for resume. It conservatively performs no automatic resubmission, within the
unified maximum retry allowance. Preview download size/operation count are
unknown. Empty or unexpected responses stop rather than implying coverage.
Only validated hashes/schema/identity/period/time/masks are reusable. Check the
worker before removing a stale lock. Private job IDs, URLs, paths and credentials
are never delivery metadata.

## Extend an existing benchmark ZIP

Use `sm-benchmark-smap-l3-assets --request REQUEST` to preview a separate L3-only
request with absent targets and no `credential_ref`. Execute with
`--execute --accept-plan PLAN_ID --watch`. Use years for full-year assets or
explicit dates for intentionally partial additions. Then preview:

```text
sm-benchmark-merge-smap --base-zip RELEASE/packages/ANCHOR/2020.zip --assets CACHE/annual/ANCHOR/2020/assets.json --output-root outputs/extended
```

Append `--execute` after review. The new ZIP preserves station targets and other
inputs, updates availability/dictionary/README/checksums, refuses conflicting L3
replacement and reuses identical verified results. It never overwrites V1 or
rebuilds the global catalogue. The base must have the public benchmark
availability/dictionary layout. This is distinct from new station-free assembly.

## Acceptance boundary

The migrated decoder/provider has a live one-cell/day sample. Unified adapter,
mixed-source assembly and restart/relocation checks are tested separately here.
See [release acceptance](smap-l3-release-acceptance.md) for actual results. These do not establish
global coverage, fresh-environment or model-session acceptance.
