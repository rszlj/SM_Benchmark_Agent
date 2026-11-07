# Sentinel-1 50 m acquisition preparation

`sm-benchmark-sentinel1` prepares Sentinel-1 for one anchor/year, with reviewed
SRTM/HWSD2/MCD12Q1 contexts and absent station targets. The profile is
`sentinel1-grd-iw-50m-v1`. It retains V1's separate physical overpasses in an annual
NetCDF rather than temporally compositing them.

## Scientific profile

Discovery uses `COPERNICUS/S1_GRD`, IW mode, 10 m source resolution, VV present,
and both ascending and descending passes. Historical VV-only scenes remain
eligible, matching the V1 recovery route. Slices are grouped by platform, absolute
orbit and pass. Relative-orbit metadata is retained from the earliest slice;
historical inconsistencies in later slices do not split the physical overpass.
Slices are ordered by time and scene ID before mosaicking.

The direct GEE export preserves the existing processing: convert VV/VH from dB
to linear power, apply `reduceResolution(mean, bestEffort=False, maxPixels=256)`,
then convert back with 10log10. Incidence angle uses the arithmetic mean. The
target is the exact EPSG:6933 260 by 260 context, nominally 50 m, supplied as WKT
and an explicit affine transform. VH is exported only when present in every
slice of the mosaic; otherwise its annual array remains NaN.

Annual output contains float32 `vv`, `vh`, `incidence_angle`, time/x/y coordinates,
platform, pass, absolute/relative orbit, acquisition ID, representative scene ID
and CRS metadata. The public source manifest retains all scene identities and
the whitelisted discovery properties. No speckle filter, new physical thresholds,
temporal compositing or gap filling is introduced. Masked pixels and absent VH
remain NaN. Corrupt or misaligned inputs stop assembly instead of being silently
excluded by the historical builder's recovery fallback.

The reported state is partial when delivered arrays contain masked pixels or
missing polarization; a complete provider-discovered list alone does not imply
every pixel/variable is available. Wholly missing VV is unavailable. Years before
2014 and empty discovery produce an unavailable manifest without an annual NetCDF.
There is no fixed acquisition calendar: counts describe discovered observations,
not proof that every historical overpass is represented.

## Agent operation and bounded work

Install `.[sentinel1]` in the project environment, including Rasterio, Xarray and
H5NetCDF/H5Py. Use the shared [official GEE login and private project setup](setup.md).
The agent creates a private request from [the example](../configs/sentinel1-request.example.json)
and prepares matching [contexts](context-preparation.md). Preview offline:

```sh
sm-benchmark-sentinel1 --request .tmp/sentinel1-request.json --context-plan PATH_TO_CONTEXT_JSON --asset-root cache/sentinel1
```

The preview does not query GEE. It explicitly includes the three context sources
and the maximum discovery/download scope. Within existing user authorization,
execute the unchanged plan with `--execute --accept-plan PLAN_ID`. The context
plan supplies the release identifier; updates require a distinct release/output
scope. Changing processing choices requires user agreement.

Discovery is limited to 4,096 scenes and 512 grouped acquisitions per anchor/year.
Exceeding either limit stops before downloading acquisitions; it never truncates
the discovered list silently. One metadata request retrieves at most 4,097 records
to detect overflow. Each acquisition response is capped at 4 MiB with a 60-second
HTTP timeout; GEE uses a 60-second request deadline. Each transient request unit
has at most two retries; permission/authentication/quota failures stop without
account switching. The uncached upper bound is 3,075 operations excluding login,
including retry attempts and URL/payload requests, and 6 GiB of acquisition payload
attempts. Actual discovered work is normally smaller and appears on later plans.

Annual assembly holds stacks in memory: at the 512-acquisition cap, the three
float32 science arrays alone total about 396 MiB; assembly needs additional memory
for temporary arrays and serialization. The agent should inspect available memory
before execution and report insufficient resources rather than silently changing
resolution or discarding observations.

Discovery and each validated acquisition are durable checkpoints. Reuse verifies
profile, code hashes, source identity, payload hash, band order, masks and exact
grid. On interruption, completed acquisitions are retained. Empty discovery is
cached too; later provider updates need a new cache/release scope. Written NetCDFs
are checked against discovery, including times, orbit metadata, units, coordinates
and NaN representation. Final annual ZIPs remain verifiable after relocation.

## Acceptance and limits

Offline tests cover slice grouping with inconsistent relative-orbit metadata,
VV-only output, masks, invalid grids/dates, bounded discovery, interruption/resume,
corrupt checkpoints, empty/out-of-period/all-masked inputs and annual delivery.
Mocked provider tests verify the VV eligibility filter, linear-power averaging
expression and exact 260-pixel export request. See [test evidence](sentinel1-test-validation.json).

Prepared 50 m acquisitions were replayed for V1 anchor `EASE2_M09km_R0403_C0871`,
year 2015 (two acquisitions). All 13 NetCDF variables/coordinates match the V1
reference in values, masks, dimensions and variable attributes, including time,
orbit and source identities. Resume and relocated ZIP verification pass. See
[replay evidence](sentinel1-replay-validation.json) and
[migration provenance](sentinel1-migration-provenance.json).

This replay uses already prepared 50 m rasters and their local metadata. It does
not independently establish raw SAR aggregation, live GEE availability, complete
provider discovery, a new-location run or fresh-environment installation. No
historical production queue, NAS inventory or original workspace is a runtime
dependency. SMAP L4, ISMN and the general multi-source scheduler remain pending.

## Date-range acceptance update (2026-11-08)

The [unified workflow](multi-source-preparation.md#user-defined-dates) now honors
exact inclusive UTC dates within each year. A [one-month online run](period-online-validation.json)
records current source-specific results: ERA5, GLDAS, IMERG, both NDVI products,
Terra LST and SMAP were available; Aqua LST was partial; Sentinel-1 discovery
returned no acquisitions. The latter does not validate live image retrieval.
Earlier offline evidence remains historical; all broader acceptance limits and
SMAP spatial-equivalence limitations remain explicit.

## Sentinel-1 live acquisition acceptance (2026-11-08)

A separate [live Sentinel-1 month test](sentinel1-online-validation.json) now
passes at EASE2_M09km_R0169_C1995 (approximately 6.302 E, 52.149 N) for April 2015.
All 11 discovered acquisitions were downloaded and processed to the existing
50 m profile; the NetCDF has 11 x 260 x 260 samples for VV, VH and incidence
angle, with no missing pixels in this case. Source validation, relocated ZIP
verification and network-blocked cache/archive reuse pass. Contexts were reused
from V1. This supersedes the earlier live-raster-unverified status for this
single tested case, without implying global, independent V1 value-equality,
clean-environment or cross-model acceptance.
