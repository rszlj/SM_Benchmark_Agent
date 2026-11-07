# Environment and GEE setup reference

The coding agent uses this reference during onboarding. New users can start with
the [README](../README.md) without running these commands themselves.

## Select the Python environment

Follow the [environment path and recovery contract](python-environment.md) first.
`scripts/python_env.py` discovers or binds an interpreter, checks dependencies and
launches registered commands with that exact Python. A local ignored record persists
the choice across agent sessions. Commands below illustrate the underlying tools;
the agent should execute them through the selected environment, not an arbitrary
PATH command. For the full GDAL workflow prefer a checkout-local Conda prefix.

## Development setup

Use Python 3.11 or newer in a dedicated environment:

```text
python -m pip install -e .
sm-benchmark-agent --request configs/request.example.json --release-root data/v1
python -m unittest discover -s tests -v
```

Planning is offline and creates no data outputs. The catalogue is included in the
GitHub checkout, not embedded in the Python wheel. Pass its location explicitly.
To locate already downloaded ZIPs, add `--package-root /path/to/release-data`,
whose `packages/` subtree mirrors the catalogue paths. After reviewing the plan,
`--execute --accept-plan <plan_id>` currently supports compatible local ZIP reuse.
The default reuse branch refuses unresolved requests. The explicit `--workflow gldas`
branch prepares four GLDAS layers and combines reviewed context assets after a
separate plan review. It does not silently invoke historical provider scripts.

The optional `sm-benchmark-export` command is an internal explicit-asset assembly
entry point. Scientific validation and annual selection precede assembly.
The core dependency is PyProj. Install the optional `[gldas]` dependencies for
Earth Engine, Parquet and context-raster validation. No production environment or
private source paths are required by the runtime.

## Configure Google Earth Engine (GEE)

The commands below use the GLDAS Python extras. For SRTM/HWSD2/MCD12Q1,
follow [context environment setup](context-preparation.md#environment), which
also requires compatible native GDAL bindings. The login and configuration
formats below are shared by all registered GEE routes. Use `.[modis]` with native
GDAL for MODIS, or `.[timeseries]` for ERA5-Land/IMERG; see
[time-series preparation](timeseries-preparation.md) for its current acceptance limits.
Sentinel-1 uses `.[sentinel1]`, including Xarray/H5NetCDF for annual assembly;
its [preparation guide](sentinel1-preparation.md) specifies resource limits and offline acceptance.

Offline catalogue planning and local package reuse need no GEE login. Follow these
steps before using a GEE retrieval adapter. The current adapter supports an
existing interactive Earth Engine login, not service-account or application-default
configuration modes.

### 1. Prepare your Google Cloud project

Use a project you own or are authorized to use. Complete the Earth Engine project
registration, enable the Earth Engine API, and ensure your Google account has
permission to use that project. Follow Google's registration process for your
actual commercial/noncommercial use; the agent does not register a project or
accept terms on your behalf. Record the **project ID**, not its display name.
See [Google's project setup guide](https://developers.google.com/earth-engine/guides/access).

### 2. Install and sign in

From this repository's root, use Python 3.11 or newer. On Windows PowerShell,
these commands use a dedicated environment without requiring shell activation:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[gldas]"
.\.venv\Scripts\earthengine.exe authenticate
```

On macOS/Linux, use `.venv/bin/python` and `.venv/bin/earthengine` instead.
Complete Google's browser sign-in using the account authorized for the project.
If that OS user already has valid Earth Engine credentials, reuse them; do not
force a new login on every run. Credentials are normally stored by Earth Engine
under `~/.config/earthengine/credentials`. Do not copy that file into this project.
See [official authentication instructions](https://developers.google.com/earth-engine/guides/auth).

### 3. Create a private project configuration

For a new configuration, copy the example once (do not overwrite an existing one):

```powershell
Copy-Item configs/credentials.example.toml credentials.toml
```

Edit `credentials.toml` locally:

```toml
[gee]
project = "YOUR_AUTHORIZED_GEE_PROJECT"
auth_mode = "interactive"
```

Replace the placeholder with your project ID. This file contains configuration,
not an OAuth token. Login credentials remain in Earth Engine's own store.
`auth_mode` is optional and defaults to `interactive`; here it selects the agent's
supported credential route, not an `earthengine authenticate --auth_mode` value.

Alternatively, use an existing `gee-config.json` with this structure directly:

```json
{
  "project": "YOUR_AUTHORIZED_GEE_PROJECT",
  "auth_mode": "interactive"
}
```

Choose **one** configuration file. The adapter reads the `[gee]` section of TOML
or the top-level JSON object; only `project` and optional `auth_mode` are accepted
there. It does not load `gee.env`, require a GitHub token, or accept the Earth
Engine login-credentials file as project configuration.

### 4. Reference the configuration in your request

Set the existing `credential_ref` field in the request JSON to the configuration
file path, for example:

```json
"credential_ref": "credentials.toml"
```

An external file is also supported, such as `"C:/private/gee-config.json"`.
Relative credential paths resolve against the command's working directory, not
the request file's directory. Forward slashes avoid JSON backslash escaping.
The configured project is passed explicitly to Earth Engine; a CLI default project
or environment variable does not replace this required setting.

### 5. Optionally check connectivity, then review the retrieval plan

For the TOML example above, this check authenticates through the existing login
and makes one tiny server computation. **It accesses GEE**, but downloads no
benchmark data and prints no configuration values on success:

```powershell
.\.venv\Scripts\python.exe -c "import tomllib, ee; c=tomllib.load(open('credentials.toml','rb')); ee.Initialize(project=c['gee']['project']); ee.data.setDeadline(60000); assert ee.Number(1).getInfo()==1; print('GEE connection OK')"
```

A successful connection is not a dataset or package validation. Next, follow the
[GLDAS pilot instructions](gldas-pilot.md) to supply matching reviewed context
assets and preview `--workflow gldas`. Planning remains offline even when a
credential reference is present. Add `--execute --accept-plan <plan_id>` only for
the reviewed retrieval scope. GEE setup alone does not prepare context assets or
enable unimplemented source adapters.

### Troubleshooting and credential handling

| Symptom | Action |
|---|---|
| `earthengine` or `ee` is missing | Install `.[gldas]` in the same environment used to run the agent; use the explicit environment executable paths above. |
| Missing/expired login | Run `earthengine authenticate` in that environment and OS account. Use `--force` only when intentionally renewing an invalid login. |
| Project not registered, API disabled, or permission denied | Check the configured project, Earth Engine registration/API status, and that the signed-in account is authorized. Ask the project administrator if needed. |
| TOML/JSON configuration rejected | Check the exact format above. `credential_ref` points to project configuration, not `gee.env` or OAuth credentials. Other authentication modes are not supported yet. |
| Quota or rate-limit failure | Stop and retain checkpoints; retry later within the authorized limits. Do not switch accounts or projects to bypass limits. |

The [Earth Engine CLI guide](https://developers.google.com/earth-engine/guides/command_line)
describes official login and project commands. Provider errors may include account
or project details: redact them before sharing logs. Never put tokens, private
keys or login-credential contents into chat, Git commits or packages. Local
`credentials.toml`, `gee-config.json`, `gee.env` and `.credentials/` are ignored by
Git; only placeholder examples belong in the public repository. Project IDs are
also excluded from public delivery metadata. User-provided context assets must
already be reviewed for public distribution.

SMAP L4 uses `.[smap]`; see [SMAP preparation](smap-preparation.md) for its
legacy sampling profile and acceptance limits.
