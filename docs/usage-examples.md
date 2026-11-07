# Usage examples: what to ask your agent

English | [简体中文](usage-examples.zh-CN.md)

Open the complete repository in a coding-agent environment that can read and
write local files and run commands. Copy these prompts into your agent; it
prepares configuration, request files and execution plans. You do not need to
write Python, JSON or TOML. See [Kimi instructions](kimi-code.md) for its entry point.

## 1. First use: check the environment only

> Read AGENTS.md and skills/extend-soil-moisture-benchmark/SKILL.md.
> Help me get started: check my local environment and the supported data sources,
> and guide me through configuration one step at a time. Do not download data
> yet, or read or display tokens, private keys or login credential file contents.

Expected: the agent explains the environment, prepares an isolated environment
if needed, and asks for missing location, dates and source choices. Offline
planning does not require GEE login. Official login and project setup are needed
only when subsequent work requires online retrieval. You complete account login
and accept provider terms yourself.

## 2. Plan one month without downloading

> I need ERA5-Land and IMERG for anchor EASE2_M09km_R0403_C0871 from
> 2015-04-01 through 2015-04-30, without station observations. Check the V1
> catalogue and local cache first. Explain what is missing, which context data
> will be included, and the preparation plan. Do not retrieve data online yet.

Expected: dates are inclusive UTC calendar dates. Date-range preparation uses
the unified entry point, without downloading a full year first and cropping it.
SRTM, HWSD2 and MCD12Q1 contexts must match the anchor and requested year.
If contexts are missing, the agent explains preparation steps and additional
download scope; it must not assume a global HWSD2 cache exists. A V1 catalogue
entry does not mean its data are available locally. The external V1 download
endpoint is not yet configured.

## 3. Download a month with Sentinel-1 acquisitions

> Retrieve Sentinel-1 for anchor EASE2_M09km_R0169_C1995 from 2015-04-01
> through 2015-04-30, without station targets. Reuse valid local contexts and
> caches first. Explain the preparation scope, then retrieve, validate and
> package this month. Guide me through GEE setup if needed. Write the output
> to outputs/my-sentinel1-april. Do not upload or publish it.

This anchor is near 6.302°E, 52.149°N. The [online acceptance run](sentinel1-online-validation.json)
retrieved 11 acquisitions and produced VV, VH and incidence-angle NetCDF data
using the existing 50 m profile. This evidence applies to that location and month;
each run still needs checks of provider coverage, masks and file contents.
The repository does not include the test ZIP or the developer's context files.

## 4. Combine multiple sources in one monthly package

> Prepare ERA5-Land, GLDAS, IMERG, Terra/Aqua NDVI, Terra/Aqua LST, Sentinel-1
> and SMAP L4 for anchor EASE2_M09km_R0169_C1995 from 2015-04-01 through 2015-04-30.
> Do not include station targets. Use the repository's existing profiles,
> explain the required contexts, and prepare and validate the sources before
> combining them into one package at outputs/my-multisource-april.
> Record missing data explicitly; do not fill gaps by interpolation.

Expected: the agent reads the selected source skills and coordinates existing
tools through `sm-benchmark-prepare`. Terra and Aqua remain separate, as do
daytime and nighttime LST. SMAP uses the historical v007 sampling method;
equivalence to native NAS/EASE cells has not been verified and must be stated.
All nine dynamic sources were available in the [integrated acceptance run](full-month-online-validation.json)
for these dates and this anchor, including 11 Sentinel-1 acquisitions. That run
reused previously live-downloaded Sentinel-1 and V1 contexts; these files are not
bundled with the repository. IMERG and SMAP ancillary nulls remain explicit.

MODIS is selected by composite **start date**. Original 8-day or 16-day composite
support is preserved and may extend beyond the last requested day. These are
not daily values; short intervals without a composite start date do not receive
fabricated observations.

## 5. Resume after an interruption

> Resume the previous task at outputs/my-multisource-april, keeping the same
> location, dates, sources and profiles. Inspect existing results and checkpoints,
> reuse validated work, and process only the remaining work. If the code,
> contexts or plan scope have changed, explain why and do not overwrite
> previously delivered packages.

Expected: recovery uses the original request and cache. Corrupt, stale or
mismatched cache entries cannot be reused directly. Authentication and server
errors must not be silently reported as source unavailability. Completed
packages are reused only when integrity and task scope match. Changes to
provenance or release version should use a new output directory.

## 6. Single-day and cross-year requests

> Plan ERA5-Land for this location on 2016-02-29 only. Do not download data.

For a single day, start and end dates are identical. Complete coverage should
contain 24 hourly records. These follow-up prompts assume a location has already
been specified; otherwise, provide coordinates or an anchor ID.

> Plan ERA5-Land for this location from 2015-12-20 through 2016-01-10, without
> downloading. Keep my requested date range; do not expand it to two full years.

The agent splits this into 2015-12-20 through 2015-12-31 and 2016-01-01 through
2016-01-10, matching contexts for each year and planning each interval separately.
A single command currently handles one anchor and an interval within one year.
This does not imply automatic large-scale batch scheduling is implemented.

## Inspecting the results

For example 3, a successful run should return:

```text
outputs/my-sentinel1-april/
  packages/EASE2_M09km_R0169_C1995/2015-04-01_2015-04-30.zip
```

Inside the package, `package_manifest.json` records scope, file checksums and
source availability. `metadata/source_manifests/` records source parameters,
actual coverage and gaps; `metadata/multi_extension.json` records workflow
provenance and validation results. Some internal filenames retain the year for
layout compatibility. Check dates, band labels and metadata for actual coverage;
a year in a filename does not imply full-year data.

Station targets are absent by design in these extensions. ISMN and private
station-file ingestion are not currently integrated. Monthly ZIPs, caches and
private configuration are not distributed through GitHub. For precise command
options, see [unified preparation](multi-source-preparation.md) and
[setup instructions](setup.md).
