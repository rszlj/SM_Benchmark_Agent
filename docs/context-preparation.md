# Static and annual context preparation

SRTM, corrected HWSD2 and annual MCD12Q1 LC_Type1 now have independent adapters.
The first workflow is bounded to one anchor/year and produces a reviewed context
plan for annual assembly. It does not retrieve other time-varying sources or
station observations. The source rules follow V1; no Terra/Aqua merging is added.

An agent should create the request/configuration and run these commands for the
user, following the root `AGENTS.md`. Users need not hand-write JSON.

## Environment

SRTM and HWSD2 derivation require native GDAL bindings in addition to Rasterio.
`pip install -e ".[contexts]"` installs the Python extras but does not install
GDAL bindings. Use compatible GDAL/Rasterio bindings already installed or prepare
the supplied Conda environment:

```text
conda env create -f environment.yml
conda run -n sm-benchmark-agent python -m sm_benchmark_agent.context_workflow --help
```

The native version pins come from the development environment used for regression
tests. A fresh Conda solve on each operating system has not been accepted yet.
Check the user's existing environment before creating another one. See
[GEE setup](setup.md#configure-google-earth-engine-gee) for official login and
the user-owned project configuration. Local-only work does not need GEE.

## HWSD2 global preparation

HWSD2 is not a GEE source. Initial preparation retrieves two official global
archives with pinned SHA-256 values, then prepares the mapping-unit raster and
SQLite database. This is a global download, even for a one-point request; size
and disk requirements are currently reported as unknown. Explain this scope
before execution. A prepared cache can instead be supplied directly and is
verified against its preparation manifest. It must contain
`HWSD2_SMU_global_compressed.tif`, `HWSD2.sqlite`, and `prepared.manifest.json`.

Preview without downloading:

```text
sm-benchmark-context hwsd-global --cache-root cache/hwsd2
```

Within the user's authorization for this scope, append
`--execute --accept-plan <plan_id>`. The result reports the prepared-cache
directory to use below. Existing official archives are hash-checked and reused.
There is no automatic retry of a failed global download. Incomplete prepared
outputs require inspection; the tool does not overwrite or accept them as valid.

## Position-based context preparation

Start from `configs/context-request.example.json`, writing the user's request
under an ignored local directory. Points or anchor IDs can be normalized by the
shared position resolver; this execution branch accepts one anchor/year.

```text
sm-benchmark-context prepare --request .tmp/context-request.json --asset-root cache/contexts --release-id extension-example-v1 --hwsd-cache cache/hwsd2/HWSD2.0-20230923/prepared
```

The preview is offline. It checks the prepared HWSD2 cache, existing context
outputs, and raw checkpoints. It reports missing prerequisites, cached work,
coverage exclusions and bounded provider operations. Cache hashing may take time
for global inputs. A plan with a missing HWSD2 prerequisite fails before starting
any remote SRTM or land-cover work.

Execute the reviewed scope by adding `--execute --accept-plan <plan_id>`.
Output is under the request's output root:

```text
contexts/<release_id>/<anchor_id>/<year>/context.json
```

This relocatable context plan lists exact grid metadata, public source manifests,
availability and checksummed assets. It can be passed as `--context-plan` to the
existing GLDAS branch when that separate retrieval scope is requested. The context
command itself never downloads GLDAS.

SRTM and HWSD2 prepared assets are reused across years of the same anchor. MCD12Q1
is cached per anchor/year. Source identities, code hashes, grids, bands, masks and
data hashes are checked before reuse. A change to preparation code makes an old
cache incompatible; use a separate cache/release instead of overwriting it.
Raw SRTM/MCD12Q1 checkpoints survive failed derivation; successful raw retrieval
does not repeat or initialize GEE on local resumption. Concurrent writers sharing
the same cache/output are not supported.

GEE raster work has at most two retries for recognized transient failures and a
60-second request deadline/HTTP timeout. Authentication, permission and quota
errors stop. Provider message text, project IDs and local paths are excluded from
public metadata. Entirely unavailable contexts are recorded explicitly; provider
failures are not relabeled as genuine data absence. Masked pixels are retained,
and source masks are decoded to float32/NaN without masking arbitrary numeric
sentinel-like values.

## Verification and remaining work

The migrated SRTM/HWSD2 scientific tests and context adapter tests run without
network access. Tests include source masks, categorical values, corrected HWSD2
weights, wrong/corrupt inputs, interruption after download, raw checkpoint reuse,
static reuse across years, and relocation of the assembled context plan.

The replay script `tests/replay_context_public_package.py` accepts explicit raw
inputs, a prepared global cache and a reference V1 ZIP. It reruns derivation and
compares every output raster value/mask/grid and the component CSV with V1.
See [replay evidence](context-replay-validation.json) and
[migration provenance](context-migration-provenance.json).

These are offline results. New GEE raster downloads, initial HWSD2 archive
download/conversion in a clean environment, and a new-location end-to-end request
have not yet received live acceptance. Remaining source migrations are listed
in the [source audit](source-tool-audit.md).
