# GLDAS extension pilot

The GLDAS branch is part of the extension agent, not a separate local product.
It supports one anchor/year and four soil-moisture layers, using prepared public
static and annual context assets. This is not yet automatic multi-source extension.
Offline replay and simulated-provider tests are distinct from live GEE acceptance.

## Fixed source profile

`gldas21-noah-four-layer-v1` selects `NASA/GLDAS/V021/NOAH/G025/T3H` and
`SoilMoi0_10cm_inst`, `SoilMoi10_40cm_inst`, `SoilMoi40_100cm_inst`,
`SoilMoi100_200cm_inst`. Values retain kg m-2 and native 0.25-degree cells selected
at the anchor centre. The fields are instantaneous, sampled every three hours.
`interval_end_utc` is the next sampling-slot boundary, not an averaging interval.
There is no spatial interpolation, depth averaging, volumetric conversion or
temporal filling. The first expected timestamp is 2000-01-01 03:00 UTC.

Source: [official GEE GLDAS catalogue](https://developers.google.com/earth-engine/datasets/catalog/NASA_GLDAS_V021_NOAH_G025_T3H).
The historical native-cell and four-layer definitions were preserved. The current
provider endpoint coverage is discovered only during authorized execution; offline
`retrievable` identifies a registered route, not a guarantee of observations.

Parquet fields match the original four-layer source representation: source image
ID, UTC start/next-slot end, native longitude/latitude, and four Float64 variables.
Masked/NaN values become null. Numeric sentinel-like values, including zero and
negative values, are preserved. Min/max and negative counts are reported, not used
for silent clipping. Estimated catalogue ranges are not hard validity bounds.
Only unique on-cadence timestamps within the year are accepted. Missing timestamps
are counted, not manufactured. Fully masked/empty results are explicitly
`unavailable/no_valid_values`; incomplete records or values are `partial`.

## Prepare and review

First follow [GEE setup in the README](../README.md#configure-google-earth-engine-gee)
for project registration, environment installation, login, configuration formats
and the distinction between an online connectivity check and offline planning.

Install `python -m pip install -e ".[gldas]"` in the project's environment.
Authenticate separately with the official `earthengine authenticate` flow.
Create a private `credentials.toml` based on `configs/credentials.example.toml`.
It references the user's authorized GEE project; OAuth credentials remain managed
by Earth Engine. The unattended adapter never switches projects or initiates login;
the coordinating agent can guide official login during user-requested setup.
An existing generated `gee-config.json` with `project` and `auth_mode:
"interactive"` is also accepted directly. Only existing interactive authorization
is supported in this pilot; other authentication modes are rejected explicitly.
The credential reference is used in place, never copied into the repository or ZIP.

Use the [context preparation workflow](context-preparation.md) to generate a
validated context plan, or supply an already reviewed one for the same anchor/year.
The context adapters have offline V1 replay acceptance; live acceptance is pending.
The plan must declare
`station_targets: "absent"`, a distinct extension `release_id`, and explicit
availability for SRTM, HWSD2, MCD12Q1 and absent-by-design ISMN. Available/partial
sources require their static or annual files. Explicitly unavailable sources must
have reasons and no data files. Include `metadata/grid.json` with the exact anchor
and the public `metadata/source_manifests/{source}.json` for all three contexts.
Each asset must specify its SHA-256. Paths are relative to the context plan.

Context validation checks checksums, file membership, source/year/anchor identity,
EPSG:6933 bounds/affine transform/dimensions and float32/NaN raster representation.
Rasters are fully decoded. It does not rerun SRTM/HWSD/land-cover derivation.
Only already scientifically reviewed public context assets may be supplied.

```text
sm-benchmark-agent --workflow gldas --request configs/gldas-request.example.json --context-plan /path/to/context.json --asset-root cache/gldas
```

The plan is offline: it reads context files and checkpoints, never authenticates.
It reports one native cell, one calendar year, four variables, up to 12 monthly
requests (36 data calls including the default maximum of two retries), and unknown
download bytes. Authentication may add provider control requests. It binds context
hashes, scientific code hashes, retry limits and scope to a plan ID.

After explicit review, append `--execute --accept-plan <plan_id>` to the same
command. Static context acquisition is not included in this branch. A missing or
incompatible context plan fails before any remote retrieval.

## Execution and resumption

Monthly JSON checkpoints have profile/native-cell/year identities and SHA-256
integrity checks. They are shared by anchors selecting the same native cell.
Already validated months are skipped. The annual Parquet and public source
manifest are staged, validated from disk, and published together. Known transient
provider errors retry with bounded backoff; authentication, permissions and quota
failures stop immediately. Raw provider exception text is not copied to state or
public metadata. Default concurrency is one; concurrent runs sharing an output
are not supported. Corrupt checkpoints fail rather than silently redownloading.
Earth Engine requests have a 60-second deadline.

An output-root SQLite database records running, verified, packaged and failed
states. Retrying the request generates a new plan when pending work changes;
review that plan ID, then execute. A valid package with the same stable scope and
code/context hashes is verified and reused; incompatible outputs are not overwritten.
No periodic polling, account switching or unbounded background jobs are launched.

The package contains the four-layer Parquet, required prepared contexts, exact
grid, public source metadata, availability, code hashes, README and file checksums.
Station targets are explicitly absent. The legacy explicit-asset v1 manifest is
currently retained; full manifest-schema unification remains a separate task.
No local credential reference, provider project ID or cache path is written into
the generated GLDAS metadata. User-supplied context assets must already be public.

## Verification

Run `python -m unittest discover -s tests -v`. Tests use an injected provider and
block network access. They cover interrupted monthly retrieval, restart, bounded
retry, quota stop, native-cell deduplication, zero/null preservation, wrong cells,
duplicate timestamps, source start, corrupted output and annual assembly.

Replay an existing public V1 package without any provider access:

```text
python tests/replay_gldas_public_package.py --source-zip /path/to/public/year.zip --output outputs/replay-new
```

The output directory must be new. The replay uses original GLDAS rows as monthly
responses, validates context rasters, compares every output row with the input,
then relocates and opens the complete package outside the repository.
This tests preservation and delivery, not live authentication/download behavior.

The initial online acceptance target is one cell for anchor
`EASE2_M09km_R0540_C0257`, year 2013, with already reviewed V1 contexts. It tests
the actual provider boundary against a known reference. A subsequent new-location
test still requires independently prepared contexts outside the V1 anchor set.

## Live acceptance, 7 November 2026

The user-authorized GEE test for the known reference cell/year passed. All 2,920
three-hourly rows and all four variable values matched the V1 reference exactly;
there were no missing timestamps or null variable values. Package reuse and
relocation were verified, including opening four context rasters from the moved
ZIP. The configured project identifier, local development paths and credential
files were absent from the package. See [online validation](gldas-online-validation.json).
This establishes this source/provider route for the tested cell/year, not arbitrary
location coverage, automatic static-context acquisition or cross-model behavior.
