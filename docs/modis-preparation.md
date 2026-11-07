# Separate Terra/Aqua MODIS preparation

Four adapters preserve the final V1 design: `mod13q1_ndvi`, `myd13q1_ndvi`,
`mod11a2_lst`, and `myd11a2_lst`. One annual package contains two separate NDVI
rasters and four separate day/night LST rasters when all four sources are selected
and available. Terra and Aqua are not fused.

## Scientific contract

Collection 6.1 NDVI uses the raw valid range [-2000, 10000], scale 0.0001 and
16-day composites on the 250 m context grid. Terra retains V1's intermediate
EPSG:4326 retrieval grid. Aqua uses the authoritative MODIS sinusoidal sphere
and the final V1 repair algorithm: bilinear reprojection of scaled values and
validity weights separately, followed by division where weight exceeds 1e-6.
This normalized convolution preserves V1's treatment of masked pixels.

Collection 6.1 LST uses paired day/night raw bands, valid range [7500, 32767],
scale 0.02 K and subtraction of 273.15 to degrees Celsius. Both platforms use
the authoritative MODIS sphere, bilinear reprojection and the 1 km context grid.
Outputs preserve 8-day composite start dates. No additional QC filtering,
temporal interpolation or platform fusion is introduced. Missing composites
remain missing and are recorded against the nominal calendar; empty collections,
periods before product availability and all-invalid outputs remain explicit.

## Agent operation

Use [setup](setup.md) for official Earth Engine login and a private authorized
project configuration. Install `.[modis]` with compatible native GDAL bindings
(needed for LST); `environment.yml` includes the source dependencies. Offline
planning needs no provider login. Prepare the matching SRTM/HWSD2/MCD12Q1
[context plan](context-preparation.md) first.

Create a private request from [the example](../configs/modis-request.example.json).
This route supports one anchor/year and absent station targets. The reviewed
plan explicitly includes all three context sources alongside selected MODIS
sources. It does not combine GLDAS or other sources through a general scheduler.

```sh
sm-benchmark-modis --request .tmp/modis-request.json --context-plan PATH_TO_CONTEXT_JSON --asset-root cache/modis
```

Inspect the returned plan and its bounded scope. Within the user's authorization,
repeat the command with `--execute --accept-plan PLAN_ID`. Changed scope or code
requires a new plan. The request's `output_root` determines delivery location;
the matching context supplies the release identifier. Choose a distinct release
for an update rather than overwriting an existing package.

Each source has an annual raw checkpoint with dates, source image identities and
hashes, followed by a validated prepared checkpoint. Direct responses are limited
to 24 MiB, HTTP payload reads time out after 60 seconds, and transient retrieval
failures have at most two retries. Authentication/permission/quota failures stop
without switching projects. Completed compatible checkpoints are reused;
corrupt or incompatible checkpoints are rejected. Empty discovery is also cached:
later provider updates require a distinct cache/release scope. This is not a
quarterly export or background-task scheduler.

Delivery checks raster values, masks, dates, grid alignment, file membership and
checksums. Public provenance excludes credential references, project IDs and raw
input paths. The ZIP remains verifiable after relocation.

## Acceptance and limits

The 50-test suite passes, including simulated retrieval, masked/empty inputs,
corruption rejection and checkpoint recovery. An independently installed wheel
replayed local raw inputs for V1 anchor `EASE2_M09km_R0540_C0257`, year 2013:
all six rasters match V1 exactly in values, masks, band dates and grids. Resume
and relocated ZIP verification pass. See [replay evidence](modis-replay-validation.json),
[test evidence](modis-test-validation.json) and [migration provenance](modis-migration-provenance.json).

Network access was blocked during replay. These checks do not establish live GEE
retrieval, new-location coverage or installation in a fresh environment. Historical
context acceptance records retain their original code hashes; the shared raster
writer now additionally preserves scientific MODIS tags.

## Date-range acceptance update (2026-11-08)

The [unified workflow](multi-source-preparation.md#user-defined-dates) now honors
exact inclusive UTC dates within each year. A [one-month online run](period-online-validation.json)
records current source-specific results: ERA5, GLDAS, IMERG, both NDVI products,
Terra LST and SMAP were available; Aqua LST was partial; Sentinel-1 discovery
returned no acquisitions. The latter does not validate live image retrieval.
Earlier offline evidence remains historical; all broader acceptance limits and
SMAP spatial-equivalence limitations remain explicit.
