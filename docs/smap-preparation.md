# SMAP L4 preparation

The `smap_l4` adapter uses profile `smap-l4-v007-legacy-13km-v1` and collection
`NASA/SMAP/SPL4SMGP/007`. It migrates the established GEE gap-fill route and V1
band/calendar definitions, without importing the original project. New NAS stack
ingestion and exact native-cell matching are not implemented.

## Scientific boundary

The historical call is `getRegion(anchor_centre, scale=13000)` without a CRS
override. The [official API](https://developers.google.com/earth-engine/apidocs/ee-imagecollection-getregion)
documents EPSG:4326 as its default. This is not evidence of exact native EASE cell
selection. Returned coordinates are retained with image IDs and timestamps;
validation checks geographic bounds, proximity (0.12 degrees) and consistency
within the year. That sanity bound is not a native transform or resampling rule.
Metadata and reviewed plans state that native-cell equivalence is unverified.

The [007 catalogue](https://developers.google.com/earth-engine/datasets/catalog/NASA_SMAP_SPL4SMGP_007)
marks this version deprecated. Version 008 is not substituted automatically.
Actual coverage is evaluated on execution; a requested recent year may be empty
or partial. The legacy calendar begins 2015-03-31 01:30 UTC and has eight slots
per day; the provider may lack some initial slots. Values retain provider units
without conversion, including the three-hour time-averaged interpretation.

Outputs retain V1's `time_utc` timestamp[ms, UTC], 45 float32 fields and ordering;
`sm_surface_anomaly` is excluded. Missing timestamps become explicit null rows,
as in the legacy partial-calendar recovery mode. This route reports partial
coverage for any year rather than requiring a separate repair run. No values
are interpolated. Masks/nonfinite values become null. Availability requires
calendar coverage and valid `sm_surface`, `sm_rootzone`, `sm_profile`; ancillary
nulls are reported separately, including peat variables. Spatial equivalence
remains unverified even for an `available` series.

## Operation

Install `.[smap]` in the project environment. Follow [setup](setup.md) for GEE.
Planning reads no credentials and makes no network calls. Use an existing
validated context plan for exactly the same anchor/year, with all three context
sources and absent targets. See [context preparation](context-preparation.md).

```powershell
sm-benchmark-smap --request configs/smap-request.example.json --context-plan outputs/contexts/context-plan.json --asset-root cache/smap
```

Review the returned scope, source profile and plan ID. Execute within the user's
authorized scope by adding `--execute --accept-plan <plan_id>`. The agent creates
the request for novice users. One anchor/year only; other workflow families need
separate output roots until integrated assembly is implemented.

Each month performs at most two server evaluations per attempt, with two bounded
retries (three attempts). A 2015 plan has at most 60 evaluations; later years 72.
Authentication is excluded from this estimate. Auth/permission/quota failures
stop without switching accounts. Checkpoints bind source, anchor, year, profile,
code hashes and content digest. Completed months are reused after interruption;
corrupt or stale cache fails validation rather than being overwritten.

The annual table and public source manifest are validated before atomic promotion.
Provider receipts record image IDs, coordinates and timestamps, not credentials or
project IDs. Delivery uses `source_cell_time_series/smap_l4/smap_l4_3hourly.parquet`,
matching V1's member name, with contexts and new provenance. It does not replace V1.

## Acceptance

`tests/test_smap_sources.py` covers calendar/value preservation, ancillary masks,
missing and empty data, interrupted-month recovery, corruption, invalid spatial
and temporal records, legacy query arguments, plan binding and relocated delivery.
`tests/replay_smap_public_package.py` replays an explicit local V1 source table.
Its image IDs and coordinates are synthetic because that table lacks receipts;
it proves table preservation and assembly only, not original sampling geometry.
See [replay evidence](smap-replay-validation.json) and
[test evidence](smap-test-validation.json). Live GEE retrieval, fresh-environment
setup and NAS/GEE spatial equivalence remain unverified.

## Date-range acceptance update (2026-11-08)

The [unified workflow](multi-source-preparation.md#user-defined-dates) now honors
exact inclusive UTC dates within each year. A [one-month online run](period-online-validation.json)
records current source-specific results: ERA5, GLDAS, IMERG, both NDVI products,
Terra LST and SMAP were available; Aqua LST was partial; Sentinel-1 discovery
returned no acquisitions. The latter does not validate live image retrieval.
Earlier offline evidence remains historical; all broader acceptance limits and
SMAP spatial-equivalence limitations remain explicit.
