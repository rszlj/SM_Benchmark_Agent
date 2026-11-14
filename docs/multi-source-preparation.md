# Unified source preparation and annual delivery

`sm-benchmark-prepare` prepares selected sources through the existing registered
adapters and assembles one annual ZIP. It supports GLDAS, four separate Terra/Aqua
MODIS sources, ERA5-Land, IMERG, Sentinel-1, SMAP L4 and SMAP L3, plus the three reviewed
context sources. No source algorithms, interpolation rules or temporal supports
are changed by assembly. This is not concatenation of independently delivered ZIPs.

SMAP L3 uses Earthdata/Harmony while other online sources primarily use GEE.
Both follow the same request dates, adapter contract and final package assembly.
Install the `smap_l3` extra and follow [Earthdata setup](smap-l3-preparation.md).
Selecting L3 does not require a second user-facing download/packaging workflow.

## Scope and setup

One anchor and a requested interval within one calendar year per invocation, absent station targets, and at
least one non-context source. ISMN and private station ingestion are outside scope.
Multiple anchors/years and automatic catalogue-versus-provider scheduling remain
future work. First reuse or prepare a matching context plan with the existing
context workflow. All three context sources are included and shown in the plan,
even if the request only names dynamic sources. Explain these prerequisites.

Install the dependency extras for selected sources, as listed in
[the source index](../skills/source-index.json). No additional dependency group is
needed for orchestration. The full [environment](../environment.yml) includes all
sources. Use [setup](setup.md) for private GEE configuration. Read the selected
source skills for scientific constraints; SMAP's native-cell equivalence remains
unverified, and a unified ZIP does not resolve that limitation.

```powershell
sm-benchmark-prepare --request configs/multi-request.example.json --context-plan outputs/contexts/context-plan.json --asset-root cache/sources
```

The agent writes request files for novice users. Planning is offline and exposes
source/profile IDs, source work states, included contexts, bounded provider call
estimates and limitations. Unknown estimates remain unknown rather than zero.
Execute an authorized unchanged plan by adding `--execute --accept-plan <plan_id>`.
Code hashes, context hashes and the request are bound to that plan. If a previously
reusable cache disappears or remaining retrieval exceeds the planned bound,
execution stops for replanning. Existing source CLIs remain usable separately;
use this unified command when selected sources span those families.

## Recovery and delivery

Sources run sequentially in stable source-ID order. Their existing monthly,
acquisition or annual checkpoints remain the durable progress record. A failure
stops execution without publishing an annual ZIP; completed work is reused on the
next run, with source validation repeated. Provider errors are not relabeled as
scientific unavailability. Only explicit source coverage results produce gaps.

Each selected source has a public manifest and availability entry, including
sources outside their product period. Available prepared files retain their bytes
and V1 member names. Context assets are included once. Provenance records profile
IDs, per-source validation results, code hashes, release ID and limitations. No
credentials, project IDs or private paths belong in public metadata. Preparation
may use private operational paths; those stay outside the archive.

Publication is atomic through the existing archive exporter. Reuse requires valid
archive integrity and matching scope identity; a different source selection or
release must not overwrite the same annual output. Use a distinct output root for
a new release. Deliveries and source caches must use separate directory trees.

## Evidence and remaining gates

`tests/test_multi_workflow.py` exercises every implemented dynamic source through
its real adapter with simulated providers and real context processing. It forces
a later-source interruption, checks earlier-source reuse, compares every packaged
source file byte-for-byte with prepared output, verifies relocated delivery, and
rejects changed plans/context/code and conflicting output scope. It also tests
explicit unavailable sources and ISMN rejection.

This is offline integration evidence. Source-specific V1 replay evidence remains
in the individual guides. A one-month live run is now recorded below. New-location acceptance, fresh-
environment installation and coding-agent behavioral trials remain pending.

Recorded test counts and build hashes are in
[multi-source validation](multi-source-validation.json).

## User-defined dates

Use `start` and `end` as inclusive UTC dates (`YYYY-MM-DD`), instead of `years`.
See [date request example](../configs/period-request.example.json). Both dates
are required. A single day is allowed. Providers receive a half-open UTC interval
ending at midnight after the requested last day. Date-range preparation uses the
unified command; family-specific commands reject date requests rather than
silently downloading the full year. Whole-V1 ZIP reuse remains annual and must
not be described as a date-cropped result.

Monthly time-series adapters retrieve only intersecting months, clipping each
provider query to the requested days. Sentinel-1 discovery is limited to the
interval. MODIS selection uses composite **start dates** within the interval;
8-day and 16-day composite values retain their original temporal support, which
can extend beyond the final date. A short interval may contain no composite
starts; no daily values or interpolated composites are invented. Missing-data
counts are measured against the requested interval, not a full year.

Static SRTM/HWSD2 contexts are reused; MCD12Q1 uses the corresponding annual
context. Period-specific caches cannot alias annual or differently dated caches.
ZIP names are `START_END.zip`; package and source manifests record the requested
period. Inner member names retain the established year-based layout for reader
compatibility; use manifests and actual timestamps/band labels for coverage.

For a request crossing calendar years, the agent must split it at year boundaries,
obtain the corresponding context plan for each year, and execute the resulting
bounded date requests. Preserve the user's original dates and authorization; never
round the first or last segment to a full year. One command invocation still
rejects a cross-year request. Do not treat this as an automatic batch scheduler.

## One-month live acceptance (2026-11-08)

[Integrated online evidence](full-month-online-validation.json) records one
package for 2015-04-01 through 2015-04-30 at `EASE2_M09km_R0169_C1995`.
All nine dynamic sources are available: ERA5-Land (720 hourly rows), GLDAS
(240 three-hourly rows), IMERG (1,440 half-hourly rows), SMAP (240 three-hourly
rows), separate Terra/Aqua NDVI and day/night LST, and 11 Sentinel-1 acquisitions.
Eight dynamic sources were retrieved online for this acceptance; Sentinel-1
reused the preceding live download at this same anchor and month. All three
context sources were reused from reviewed V1 assets.

Source validators passed. The relocated ZIP passed integrity checks; its tables,
rasters and NetCDF were decoded and checked for the requested dates. With socket
access blocked, all nine source caches were prepared and validated again, and
the complete archive was reused with zero planned provider operations. IMERG
microwave ancillary values and some SMAP ancillary fields contain nulls, retained
explicitly without interpolation. SMAP's native-cell equivalence remains unverified.
This does not establish fresh-environment installation, live context acquisition,
general new-location coverage or cross-model acceptance.

The [earlier month at another anchor](period-online-validation.json) and the
[preceding Sentinel-1 run](sentinel1-online-validation.json) remain historical
evidence; the integrated case above is the primary monthly acceptance example.

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
