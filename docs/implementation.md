# Extension agent implementation and acceptance

## Deliverables

The final deliverables are the fixed V1 dataset hosted outside GitHub and an
extension agent maintained in this repository. Local planning and assembly are
internal capabilities, not a separately released product. No complete extension
or cross-model success is claimed at this stage.

## Implemented foundation

- Stable request and plan IDs, point/bbox/anchor selectors, inclusive date or year
  selection, explicit registered source IDs, target mode and package-count limit.
- Exact EASE2 anchor/context geometry and existing ERA5-Land/GLDAS/IMERG native-cell
  selection functions. No independent scientific formulas were introduced.
- V1 catalogue lookup independent of external package storage. A catalogue match
  is distinct from a locally reusable file and retains its hash/size/path.
- Local ZIP reuse with complete member, CRC, size and SHA-256 checks; SQLite
  execution state; interruption recovery and refusal to overwrite corrupt output.
- Explicit station-free asset assembly declaring targets absent by design.
  This checks integrity, not arbitrary scientific source semantics.

The shared modules were migrated from the development project without importing
its initializer, provider modules or scripts. Their original hashes are recorded
in `migration-provenance.json`; this repository is now their independent source.
The Python namespace is `sm_benchmark_agent` and does not overlap the old toolkit.

## Adapter boundary

`adapters.py` defines `plan`, `prepare`, `validate`. The default registry now
contains twelve adapters: GLDAS, SRTM/HWSD2/MCD12Q1, four separate Terra/Aqua
NDVI/LST sources, ERA5-Land, IMERG, Sentinel-1 and SMAP L4. Sentinel-1 uses
`sm-benchmark-sentinel1` with bounded discovery and acquisition checkpoints;
prepared 50 m acquisition replay passes, while live retrieval remains unverified.
See [Sentinel-1 preparation](sentinel1-preparation.md).
ERA5-Land and IMERG use `sm-benchmark-timeseries`;
monthly checkpoints and V1 source-table replay pass offline. Their live retrieval
remains unverified. See [time-series preparation](timeseries-preparation.md).
The MODIS route uses `sm-benchmark-modis` with a matching context
plan; six annual rasters pass exact V1 offline replay. Live MODIS retrieval remains
unverified. See [MODIS preparation](modis-preparation.md).
The context workflow is exposed through `sm-benchmark-context`; see
[context preparation](context-preparation.md) for its offline acceptance and live-test limits.
Other catalogue source names do not imply
download support; unimplemented adapters raise `NotImplementedError`. The GLDAS
branch is explicitly selected using `--workflow gldas`; it is not an automatic
multi-source scheduler. See [GLDAS pilot](gldas-pilot.md).

A source profile must fix product/version, variables, units, spatial and temporal
support, missing-value policy, processing parameters and validation rules. Offline
planning inspects local holdings and coverage. Authorized preparation uses a user
credential reference, bounded work and retries. Authentication/quota errors must
not trigger account switching. Work keys include profile, native cell or context
and period so shared retrieval can be deduplicated. Validators inspect output
files rather than trusting exit codes. Public metadata must exclude credentials,
project IDs, private logs and local paths.

First implemented adapter: GLDAS-2.1 Noah's four native soil-moisture layers. The historical
single-cell tool exports 36 variables and includes a project ID in its private
manifest; the new adapter uses the four-layer profile, records instantaneous
temporal support and writes public metadata without project IDs. Monthly
checkpointing, scientific output validation and prepared-context assembly pass
simulated-provider and real-data replay tests. One live user-authorized GEE cell/year test now passes, including value-for-value
comparison with V1 and relocated package verification. See
[gldas-online-validation.json](gldas-online-validation.json). New-location
multi-source validation remains pending.

## Next acceptance gates

The [source-tool migration audit](source-tool-audit.md) inventories all 13 V1
source IDs, reusable legacy routes, profile differences and public-readiness gaps.
It is a code inspection, not an additional live acceptance result.

1. Extend native-cell/month checkpoint discovery to general prepared-asset discovery.
   The GLDAS adapter now checks gaps, nulls, timestamps and native-cell identity.
2. Accept live static/annual context preparation. Independent SRTM/HWSD2/MCD12Q1
   preparation and context-plan assembly now pass offline tests and V1 replay.
   Fresh provider retrieval and clean-environment global preparation remain pending.
3. Run a small user-authorized request outside V1 coverage, including retrieval,
   restart, validation and relocated annual delivery. Record scientific checks.
4. Validate the unified one-anchor/year workflow with live providers and a new location.
   Offline multi-source assembly and recovery are implemented; larger batch scheduling
   remains pending. ISMN ingestion is outside scope; SMAP native-cell equivalence
   remains unverified.
5. Configure the real V1 hosting endpoint and implement verified remote package reuse.
6. Run reproducible model-agent tasks with actual model IDs, dates and tool logs.

Do not describe these gates in the manuscript as completed before evidence exists.

## Request behavior

Exactly one spatial selector is accepted: `points` as lon/lat pairs, `bbox` as
west/south/east/north, or `anchor_ids`. Bbox edges include their containing cells;
antimeridian ranges must be split. `years` selects full calendar years. Unified preparation honors inclusive
`start`/`end` dates within a year; cross-year requests need per-year segments
and matching contexts. Whole-package catalogue reuse remains annual. `station_targets` is required, optional or absent.
Whole-ZIP reuse includes unselected sources and any existing station targets,
preserving source gaps; absent mode cannot reuse a station-bearing ZIP.

The source catalogue does not promise retrieval beyond its recorded coverage.
`credential_ref` is an optional private operational reference, never opened by
offline planning or embedded in delivered packages. Relative output paths resolve
against the working directory. Planning fails excessive scope before enumeration.
Atomic ZIP publication requires hard-link support (for example NTFS). Reuse and
scope planning access no provider; explicit source preparation can access the
configured provider. Provider terms remain the user's responsibility.

SMAP L4 v007 now has an independent legacy GEE sampling adapter, monthly
checkpoints and annual delivery. Offline V1 table replay passes; live retrieval
and native EASE-cell equivalence remain unverified. See
[SMAP preparation](smap-preparation.md).

## User-supplied station data scope (2026-11-08)

ISMN ingestion is not part of the current migration plan. Existing V1 station
targets and the catalogue source identity remain intact. Current source-preparation
workflows deliver inputs and metadata with station targets absent by design.
A future optional station interface should accept authorized user-supplied data,
including private observations, without assuming ISMN format or provenance. Its
schema, quality flags, units, temporal support and target rules require a separate
contract before implementation. Private observations must not be published or
included in distributed packages without explicit user authorization. No generic
station ingestion capability is currently implemented.

Unified source preparation now supports selected source families in one
anchor/year package with matching prepared contexts and absent targets. It uses
existing adapters and checkpoint recovery. See [unified preparation](multi-source-preparation.md).
Live integrated and multi-anchor/year acceptance remain pending.

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
