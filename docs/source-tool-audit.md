# Source-tool migration audit

Audit date: 2026-11-07. This is a read-only code inventory, not a new execution
or online acceptance result. No downloads, authentication, production-data changes
or source migrations were performed during this audit.

Subsequent implementation on the same date migrated SRTM/HWSD2/MCD12Q1 and added
offline tests and V1 replay. See [context preparation](context-preparation.md).
The inventory below preserves the state at audit time.

## Finding

The development workspace contains acquisition or local-ingestion code for all
13 source IDs in the V1 catalogue. It does not contain 13 interchangeable,
public-ready adapters. The independent agent repository registers only GLDAS21.
Existing source tests and completed V1 delivery are useful migration evidence,
but do not demonstrate that a clean checkout can prepare every source at a new
location. The agent cannot yet fulfill that complete request.

Legacy file references below are relative to the development repository and are
evidence for migration, not runtime dependencies of this repository. `sources/`
means `src/soil_moisture_benchmark/sources/`. Paths in the final public runtime
must not require that repository, its original environment, NAS, or inventories.

## Source-by-source inventory

Except for GLDAS21, none of these preparation routes is registered in the public
agent. Catalogue recognition and existing-package reuse are separate capabilities.

| Source ID | Existing location-based route | V1-relevant processing and evidence | Work before public use |
|---|---|---|---|
| `srtm` | `srtm-tile`; `sources/gee_srtm.py:download_gee_srtm_tile` accepts an exact context and authorized project. NAS conversion is an alternative production route. | Local terrain derivation followed by aggregation to the 50 m context; `test_gee_srtm.py` checks Horn derivatives and alignment. | Migrate retrieval and derivation without NAS inventories; normalize public masks/provenance; validate coverage, cached outputs and terrain bands. GDAL environment setup is required. |
| `hwsd2` | `hwsd2-tile`; `prepare_hwsd2_global` downloads official archives, prepares a raster and SQLite database; `extract_hwsd2_tile` selects a context. No GEE needed. | Mapping units, component table and seven-layer weighted properties. The library already excludes negative missing codes before renormalizing weights. `test_hwsd2.py` covers extraction and no-soil output. | Migrate the complete initial global preparation route, archive verification and tile extraction. Explain initial global-cache cost; validate prepared cache before reuse; include `access-parser` and compatible raster/GDAL dependencies. Preserve the corrected V1 profile. |
| `mcd12q1` | `mcd12q1-tile` offers GEE annual retrieval. V1 LC_Type1-specific GEE retrieval also exists in `fill_mcd12q1_lulc_gaps.py` and `download_mcd12q1_lulc_2025.py`. | `sources/mcd12q1_lulc.py` processes the V1 class stack; tests cover nearest-neighbour categorical reprojection. The generic GEE tool selects more bands. | Extract a parameterized annual LC_Type1 route from production logic; remove fixed year/inventory assumptions; preserve classes, native CRS, 500 m alignment and actual coverage. Do not publish the generic multiband output as if it were the V1 profile. |
| `mod13q1_ndvi` | `sources/mod13q1_ndvi.py:download_gee_mod13q1_ndvi_year` accepts year/context/project; NAS-stack ingestion also exists. | Separate Terra 16-day NDVI, scale conversion and 250 m reprojection; `test_mod13q1_ndvi.py`. | Migrate the separate-platform path, parameterize snapshot defaults, add output validation and checkpoint handling. Avoid substituting the combined `modis-vi-tile` profile. |
| `myd13q1_ndvi` | GEE orchestration is in `scripts/download_myd13q1_ndvi.py`, using the shared NDVI derivation; correction/rebuild logic is in `rebuild_myd13q1_from_local_raw.py`. | Separate Aqua series; explicit MODIS authalic-sphere CRS correction. Tests cover Aqua metadata and the CRS override. | Move script orchestration into a reusable adapter; preserve the corrected CRS override and platform coverage; remove production queues/paths. Merely copying the original generic MODIS downloader is insufficient. |
| `mod11a2_lst` | `download_mod11a2_lst_all_anchors.py` contains chunk preparation, GEE download and bounded retry; `sources/mod11a2_lst.py` performs derivation. | Separate Terra day/night 8-day stacks, scale/unit conversion and 1 km context; `test_mod11a2_lst.py`. | Extract a one-context/year route with durable chunk checkpoints, selected V1 variables, calendar validation and sanitized metadata. The combined `modis-lst-tile` route is a different profile. |
| `myd11a2_lst` | `download_myd11a2_lst_all_anchors.py` reuses functions from the Terra production script and calls shared derivation with the Aqua product. | Separate Aqua day/night 8-day stacks. Some tests exercise shared derivation; that is not an independent Aqua live acceptance. | Replace script-to-script imports with library helpers; preserve platform-specific dates/profile and add Aqua-specific acceptance. |
| `sentinel1` | `sentinel1-tile`, `sentinel1_workflow.py` and `sources/gee_sentinel1.py` query/group acquisitions and retrieve scenes. Production scripts add queues and recovery. | Slice grouping and backscatter aggregation tests exist. V1 annual NetCDF assembly is in the production package builder. | Fix the benchmark route to the reviewed 50 m representation; generic CLI default is 10 m. Separate offline scope planning from online scene discovery; migrate acquisition checkpoints and annual stacking; validate orbit, polarization, time and missing-data metadata. |
| `era5_land` | `gee-era5-land-period`; separate CDS download route; V1 NAS-compatible GEE gap retrieval in `fill_era5_land_gaps.py`. | Native-cell hourly series. `test_gee_era5_land.py` explicitly distinguishes core hourly-accumulation and raw NAS-compatible profiles; `nas_era5_land.py` normalizes imported time series. | Select the exact V1 variable/accumulation profile before migration; extract native-cell/month retrieval and validators; do not interchange CDS, core GEE and NAS-compatible outputs silently. |
| `gldas21` | Public `gldas21.py` and `gldas_workflow.py` already implement the four-layer pilot. Legacy single-tile code exports a broader band set. | Public monthly checkpoints, scientific validation, retry limits and one live reference-cell/year comparison are recorded in `gldas-online-validation.json`. | Keep current status; no further GLDAS work in this audit. General multi-source/new-location orchestration remains pending, and current delivery needs reviewed context assets. |
| `imerg_v07` | `imerg-v07-tile`; `download_imerg_v07_all_anchors.py` has native-cell batching, temporal splitting, retry and validation logic. | Native 0.1-degree half-hourly time series. `test_gee_imerg_v07.py`, `test_download_imerg_v07_all_anchors.py`; separate `validate_imerg_v07_years.py`. | Extract parameterized cell/period work, retain partial-calendar/value semantics, add durable checkpoints and public manifests. Remove station-year/inventory coupling and bound request size/retries. |
| `smap_l4` | `smap-l4-year`; `sources/gee_smap_l4.py` supports GEE yearly retrieval in chunks; `sources/smap_l4.py` processes local monthly inputs. | Existing tests check product-start calendar and monthly array/time decoding. NAS inventory conversion and GEE gap-fill workflows also exist. | Preserve product/version and validate exact native-cell support against V1. The GEE route uses `getRegion(..., scale=13000)`; this warrants a projection/cell-equivalence check, not an unreviewed change. Add chunk persistence, output validation and independent provider acceptance. |
| `ismn` | `prepare-ismn-release` ingests supplied local station files; archive/update scripts handle existing downloads. It is not an arbitrary-location station downloader. | `ismn.py`, `targets.py`, `ismn_workflow.py` implement station parsing and target rules; target and workflow tests exist. | Provide user-supplied authorized data ingestion, spatial/time selection and explicit no-station behavior. Parameterize fixed archive-script dates and preserve all target rules. Never infer observations from coordinates or invent station targets. |

## Cross-cutting gaps

V1 packaging check (2026-11-07): inspected the actual
`EASE2_M09km_R0540_C0257/2013.zip` and its four MODIS source manifests, alongside
the production builder's separate source loops. Terra and Aqua are in the same
annual ZIP but remain separate datasets/files. This example has one 23-band
16-day NDVI TIFF per platform and separate 46-band 8-day day/night LST TIFFs per
platform. The NDVI dates retain the Terra/Aqua offset. They are not fused into a
single time series. Preserve this V1 delivery structure during migration; these
sample counts are evidence for 2013, not universal completeness requirements.

1. **The generic CLI is not the V1 scientific profile registry.** Combined
   Terra/Aqua NDVI/LST, multiband land cover, broad GLDAS fields, and ERA5
   accumulation alternatives coexist with the production-specific routes. Migrate
   the V1 definitions intentionally; do not expose every historical option by default.
2. **Prepared data are not automatically public data.** Some legacy rasters use
   integer types or numeric NoData. The production delivery helper
   `scripts/revise_public_trial_package.py:copy_public_tiff` converts masked
   arrays to float32/NaN and filters tags. Its metadata helpers remove internal
   provenance. Several acquisition manifests directly contain `project` and local
   paths. Public adapters must produce the reviewed representation and public
   metadata, not copy private acquisition manifests into a package.
3. **Existing-file checks are often weaker than validated resumption.** Many
   legacy functions skip work when data and manifest paths exist. Selected batch
   scripts add checksums, validation or retries, but this is not one common
   guarantee. Each migrated work unit needs identity/hash/schema verification,
   atomic publication and bounded source-specific recovery.
4. **Offline planning must remain offline.** Sentinel-1 acquisition planning
   queries provider metadata before its download flag is checked. Separate the
   local scope preview from authorized online discovery. Do not call historical
   CLI previews assuming every one is network-free.
5. **Environment setup remains a real dependency.** The old project explicitly
   installs GDAL bindings via its Conda environment; PyProj alone is insufficient.
   Raster, table, NetCDF and HWSD database capabilities need tested optional
   dependency groups and a reproducible setup path. This audit did not test a
   fresh Windows, Linux or macOS environment.
6. **Annual delivery contains additional scientific preparation.** The production
   builder performs annual subsetting, Sentinel-1 stacking, source-cell mapping,
   public representation conversion and metadata construction. Public explicit
   asset assembly does not replace these operations. These reusable functions
   need separation from release IDs, audit files and fixed production snapshots.
7. **Capabilities must be visible to the coordinating agent.** The public registry
   currently has only one adapter. A source name in `catalogue.py` is a catalogue
   column mapping, not evidence of acquisition support. Per-source capability and
   unmet-prerequisite reporting should drive the user conversation.

## Proposed migration sequence

This is an implementation order, not authorization to launch downloads.

1. Freeze a public profile/capability table and share the existing position/grid
   resolver. Keep geographic coverage, temporal support, masks, units, variables,
   resampling and validation requirements explicit for each source.
2. Migrate SRTM, HWSD2 and annual MCD12Q1. These establish static/annual contexts
   needed by subsequent complete annual delivery. HWSD2 global preparation is a
   separate bounded operation, not an invisible cost of a one-point request.
3. Migrate separate-platform NDVI and LST using shared low-level helpers, then
   ERA5-Land and IMERG using validated native-cell/time work units.
4. Migrate Sentinel-1 acquisition/annual assembly and SMAP L4 with focused spatial
   and temporal acceptance. Retain existing GLDAS evidence without expanding its
   claim to untested locations or sources.
5. Add optional ISMN ingestion and the full multi-source scheduler, annual
   assembly, source-gap reporting and restart behavior. A station-free request
   must not depend on the developer's station inventory.
6. Test a clean checkout through a novice-style agent session. Require a bounded
   new-location example, interrupted/resumed execution and relocated delivery
   before claiming the complete workflow. Configure verified V1 package access
   separately when the external hosting endpoint is available.

For each migrated source, acceptance includes an offline scope preview, an
explicit profile, a local fixture/replay test, invalid-cache and interrupted-work
tests, output validation, public metadata checks and a bounded authorized online
test where acquisition is involved. Existing source gaps must remain explicit.

## Evidence and limits

This audit inspected source definitions, CLI dispatch, relevant production
scripts, test definitions and existing public validation records. Tests were not
rerun, and current provider availability, URLs, account access and quota were not
probed. The presence of a test means coverage exists in code, not that this audit
executed it successfully. No claim of clean-environment or cross-model acceptance
is made.

Key legacy evidence locations:

- `src/soil_moisture_benchmark/__main__.py`: position-based CLI dispatch and
  source-specific defaults.
- `sources/hwsd2.py:314`: official global preparation; `:402`: tile extraction;
  component-weight missing-code correction in the same function.
- `sources/gee_modis_vi.py:388` and `sources/gee_mod11a2.py:322`: combined
  platform download routes; V1-specific alternatives are listed in the table.
- `sources/gee_smap_l4.py:121`: GEE sampling call to verify during migration.
- `scripts/revise_public_trial_package.py:90`: public raster conversion;
  `:394`: public source metadata construction.
- `scripts/package_benchmark_release.py:279`, `:410`, `:557`: annual subsetting,
  Sentinel-1 stacking and production asset preparation.
- `pyproject.toml` and `environment.yml`: dependencies and native GDAL setup.

Public repository evidence: [implementation status](implementation.md),
[adapter registry](../src/sm_benchmark_agent/adapters.py),
[GLDAS acceptance record](gldas-online-validation.json).

## MODIS migration follow-up (2026-11-07)

Four separate MODIS adapters are now implemented. The final V1 Aqua NDVI route
requires the correction in `scripts/rebuild_myd13q1_from_local_raw.py`, including
normalized convolution of values and validity weights; the generic NDVI kernel
alone does not reproduce the final V1 package. All six annual MODIS rasters now
match V1 exactly in offline raw replay. Live acquisition is still pending. See
[MODIS preparation and evidence](modis-preparation.md). The original audit above
remains a historical code inspection.

## ERA5-Land/IMERG migration follow-up (2026-11-07)

Both native-cell adapters now support monthly checkpoints, written-table validation
and station-free annual assembly. The raw18 ERA5 profile and IMERG source statuses
are preserved. Offline source-table replay matches the inspected V1 tables exactly.
The inspected ERA5 manifest overstates availability despite variable gaps; new
output reports partial without modifying V1. Live retrieval remains unverified.
See [time-series preparation and evidence](timeseries-preparation.md).

## Sentinel-1 migration follow-up (2026-11-08)

The independent 50 m route now supports bounded discovery, physical-overpass
grouping, acquisition checkpoints and annual NetCDF assembly. Historical VV-only
observations are retained with NaN VH, following the recovery route rather than
the generic dual-pol query. Prepared-acquisition replay matches all variables
and coordinates in one V1 reference year; live GEE remains unverified. See
[Sentinel-1 preparation and evidence](sentinel1-preparation.md).

## SMAP migration update (2026-11-08)

The legacy GEE v007 sampling route is now implemented independently with monthly
checkpoints, validation and annual packaging. The original native-cell equivalence
gate remains open: offline source-table replay cannot establish NAS/GEE spatial
equivalence. See [SMAP preparation](smap-preparation.md) and
[migration provenance](smap-migration-provenance.json). This update does not
turn the earlier inspection into live acceptance.

## Station scope update (2026-11-08)

The earlier recommendation to migrate ISMN ingestion is deferred out of the
current scope by user decision. Prioritize multi-source orchestration and annual
assembly. Future station ingestion should be provider-independent and support
authorized private observations; no ISMN-specific skill or adapter is planned
for the current delivery. Existing V1 catalogue identities and targets are retained.
