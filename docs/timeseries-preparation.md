# ERA5-Land and IMERG native-cell preparation

`sm-benchmark-timeseries` prepares selected ERA5-Land/IMERG sources for one
anchor/year and assembles them with reviewed SRTM/HWSD2/MCD12Q1 contexts. Station
targets must be absent. It is not yet the complete multi-source scheduler.

## V1 profiles

| Source | Profile and representation |
|---|---|
| ERA5-Land | `benchmark-raw18-nas-compatible-v1`: 18 raw hourly fields from `ECMWF/ERA5_LAND/HOURLY`, NAS-compatible variable names, float32 values, millisecond UTC timestamps. Accumulated fields remain raw forecast accumulations; they are not hourly increments. |
| IMERG | `imerg-v07-native-half-hourly-v1`: nine fields from `NASA/GPM_L3/IMERG_V07`, float64 values, microsecond UTC timestamps, image IDs, native coordinates and permanent/provisional/unknown status. Precipitation remains mm h-1, not half-hour depth. |

The existing native-cell functions select the cell containing the anchor centre.
ERA5's transform starts at (-180.05, 90.05); IMERG's at (-180, 90). Neither source
is interpolated onto a fine raster. The interval-end label marks the next hourly
or half-hourly slot; it does not change the physical support of the raw variables.

IMERG's historical missing-band harmonization retains the production sentinel
only in provider transport; output stores missing values as Arrow nulls. Nonfinite
provider values also become null. Zero and finite negative values are retained.
No new QC thresholds, aggregation, deaccumulation or gap filling are introduced.
Missing timestamps remain absent, with counts against the full nominal calendar.
Requests before 1950 (ERA5) or 1998 (IMERG) produce unavailable metadata and an
empty typed table without contacting GEE. Later years still require actual coverage
checks; registration of a route does not promise data exist for every year.

ERA5 is partial if timestamps or any variable values are missing. IMERG reports
ancillary microwave/IR null counts without treating every such null as failure;
missing timestamps, missing precipitation or non-permanent status cause partial
availability. Empty collections and wholly masked results are unavailable.

## Agent operation

Install `.[timeseries]` in the project environment. Use [GEE setup](setup.md) for
the same official login and private project configuration as the other adapters.
The agent creates a private request from
[the example](../configs/timeseries-request.example.json), prepares matching
[contexts](context-preparation.md), and previews:

```sh
sm-benchmark-timeseries --request .tmp/timeseries-request.json --context-plan PATH_TO_CONTEXT_JSON --asset-root cache/timeseries
```

Within the user's authorization, execute the unchanged plan by adding
`--execute --accept-plan PLAN_ID`. The preview explicitly includes all three
context sources. Its release identifier comes from the context plan. Give updates
a new release and output scope; existing annual ZIPs are never silently replaced.
Scientific profile changes require user agreement. Credentials and configuration
references are excluded from public source and package metadata.

Work is keyed by profile, native cell and year; nearby anchors sharing a native
cell can reuse validated source tables. Each monthly checkpoint binds identity,
profile, code hashes and payload hash. Prepared tables are checked for exact
schema, native cell, timestamps, cadence, units, nulls and status. Corrupt or
incompatible checkpoints fail rather than being reused. Existing compatible work
resumes without another login. Empty provider months are cached too: later provider
updates require a new cache/release scope.

Each retrieval unit is one cell/month, with at most two transient retries and a
60-second GEE request deadline. The plan bounds evaluations excluding login:
at most 72 for a fully missing ERA5 year and 108 for IMERG. There is no unbounded
recursive splitting, account switching or hidden global download. Provider size
failures stop while preserving completed months. Download bytes are not predicted.

## Acceptance and known limits

Offline tests cover both profiles, raw-value retention, missing-band conversion,
provisional data, missing timestamps, empty/all-masked/out-of-period inputs,
wrong-cell/cadence rejection, checkpoint recovery, corruption and annual delivery.
The shared archive builder also has a Windows long-path regression check: its
temporary tree no longer repeats the final packages/anchor directory hierarchy.
See [test evidence](timeseries-test-validation.json).

Local preprocessed source tables for `EASE2_M09km_R0540_C0257`, year 2013, were
replayed into monthly work units and repackaged. ERA5's 8,760 rows and IMERG's
17,520 rows match the V1 tables exactly in schema, timestamps, values and nulls.
Resume and relocated ZIP validation pass. This is a **source-table replay**:
it does not independently validate GEE sampling or upstream source processing.
The ERA5 input table has no provider image IDs, so replay uses synthetic timestamp
IDs; actual retrieval uses provider IDs. See [replay evidence](timeseries-replay-validation.json)
and [migration provenance](timeseries-migration-provenance.json).

The reference ERA5 source manifest says available although 16 of 18 variables
are wholly null and the two remaining variables have gaps. The extension preserves
these values and correctly reports partial. The fixed V1 package is not modified;
this observation is limited to the inspected source-year, not a full V1 audit.

Live retrieval, fresh-environment installation and a new-location end-to-end run
remain unverified. The tested runtime does not import the development toolkit or
require its local inventory. Local historical NAS ingestion/merging is not exposed
as part of this new GEE route.

## Date-range acceptance update (2026-11-08)

The [unified workflow](multi-source-preparation.md#user-defined-dates) now honors
exact inclusive UTC dates within each year. A [one-month online run](period-online-validation.json)
records current source-specific results: ERA5, GLDAS, IMERG, both NDVI products,
Terra LST and SMAP were available; Aqua LST was partial; Sentinel-1 discovery
returned no acquisitions. The latter does not validate live image retrieval.
Earlier offline evidence remains historical; all broader acceptance limits and
SMAP spatial-equivalence limitations remain explicit.
