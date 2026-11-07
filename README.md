# Soil Moisture Benchmark Agent

An agent-assisted workflow for extending the Global Soil Moisture Benchmark to
user-specified locations, periods and registered data sources.

> **Development preview for external testing ? not a stable release.**
> One-location/month online checks have passed. Fresh-environment installation
> and Kimi model-session acceptance remain pending. Start with a small request;
> see [examples](docs/usage-examples.md) and [environment setup](docs/python-environment.md).

## Start with your coding agent

1. Get a local copy of this repository. You can fork it on GitHub and clone your
   fork, clone this repository directly, or download and extract its ZIP. A fork
   is optional; it creates your own GitHub copy, not a local folder.
2. Open the local repository folder in a coding-agent environment such as Codex
   or Claude Code, or Kimi Code, with permission to read files and run local commands.
3. Send the following message (either language works):

> Read AGENTS.md and skills/extend-soil-moisture-benchmark/SKILL.md.
> Help me get started. Check my environment, guide me through any required
> configuration one step at a time, and ask what location and years I need.

> 请阅读 AGENTS.md 和 skills/extend-soil-moisture-benchmark/SKILL.md。
> 帮我开始使用：检查环境，逐步引导必要的配置，再询问我要处理的地点和年份。

You do not need to write Python, prepare JSON/TOML files, or install the skill
separately. The agent reads the instructions from this checkout, checks for a
suitable Python environment, installs project dependencies, and prepares request
and configuration files. Python 3.11+ is a runtime requirement: if it is missing,
the agent helps you install it using a method appropriate for your computer.
Agent software, network access and provider access remain prerequisites.

The entry skill coordinates twelve separate source skills and reads only those
needed for your request. Setup and delivery rules are shared; users still interact
with one agent. See [skill organization](docs/skill-layout.md) for maintenance details.

Tell the agent your location (coordinates or extent), time period, and data needs
in ordinary language. It will explain the supported options, check V1 coverage,
and show the scope and missing inputs before starting an extension. Existing
configuration and completed work are reused where valid.

Kimi Code uses the same tools and instructions. A small discovery entry is
provided under `.agents/skills/sm-benchmark/`; see [Kimi setup and acceptance
status](docs/kimi-code.md). No Kimi model session has yet been validated.

### Example requests

See [copy-and-paste usage examples](docs/usage-examples.md) for first-time setup,
offline planning, a Sentinel-1 month, multi-source delivery, resuming interrupted
work, and single-day/cross-year requests. The agent creates the configuration and
request files; users describe the task in ordinary language.

### Configure Google Earth Engine (GEE)

Only workflows that retrieve from GEE need GEE setup. The agent guides you
through project setup and official browser login when needed, then writes the
local configuration. You supply an authorized Google Cloud project ID or the
path to an existing configuration; never paste tokens or private keys into chat.
Account registration, terms and browser sign-in require your own participation.
Offline planning can begin without GEE.

The agent follows the [environment and GEE setup reference](docs/setup.md).
This reference is also available if you prefer manual setup.

## Status

The complete extension agent is under development. Request normalization, offline
catalogue planning, verified local package reuse and explicit asset assembly are
implemented as internal foundations. These are not a separate local-only product.
The first GLDAS retrieval/validation/assembly branch is implemented and tested
with simulated providers, offline real-data replay and one live GEE cell/year
acceptance. End-to-end new-location multi-source extension remains pending. See
[GLDAS pilot](docs/gldas-pilot.md) and [implementation status](docs/implementation.md).

SRTM, corrected HWSD2 and annual MCD12Q1 context preparation have now been migrated
and tested offline, including comparison with a V1 reference package. See
[context preparation](docs/context-preparation.md). Their live acquisition and
clean-environment acceptance remain pending.

Separate Terra/Aqua NDVI and day/night LST adapters are also migrated. All six
annual rasters match a V1 reference package exactly in offline raw-input replay;
a one-month live run also passes with Aqua LST masking recorded. See [MODIS preparation](docs/modis-preparation.md).

ERA5-Land raw hourly and IMERG half-hourly native-cell preparation now support
monthly checkpoints and annual delivery. Offline source-table replay matches V1;
one-month live retrieval also passes. See [time-series preparation](docs/timeseries-preparation.md).

Sentinel-1 now has bounded discovery, acquisition checkpoints and V1-compatible
50 m annual NetCDF assembly. Prepared-acquisition replay and a separate one-month live GEE retrieval
test pass. See [Sentinel-1 preparation](docs/sentinel1-preparation.md).

The intended workflow resolves requests to EASE-Grid anchor cells and calendar
years, checks existing coverage, reuses compatible data, retrieves missing inputs
with user-authorized tools, validates outputs and assembles annual packages.
Extensions without station observations will contain inputs and metadata without
station targets.

## Repository structure

- `src/`: orchestration, source adapters, processing and validation.
- `skills/`: instructions for agent-assisted execution.
- `configs/`: configuration examples without credentials.
- `tests/`: reproducible tests and acceptance tasks.
- `docs/`: installation, scientific contracts and usage documentation.
- `data/v1/`: V1 release metadata and catalogue only.

## Data and credentials

The V1 dataset and the extension software are separate deliverables. Annual data
packages will be hosted outside GitHub. The V1 catalogue will link available
packages to their download locations and integrity information.

Users supply their own provider credentials and authorized projects. Credentials,
downloaded data, generated packages and local environments must not be committed.
Historical production and recovery scripts are not part of this repository.

SMAP L4 v007 now has an independent legacy GEE sampling adapter, monthly
checkpoints and annual delivery. Offline V1 table replay passes; live retrieval
and native EASE-cell equivalence remain unverified. See
[SMAP preparation](docs/smap-preparation.md).

Station-data ingestion is outside the current extension scope. Users may have
private observations rather than ISMN data; a future optional interface will need
a separate data contract. Current preparation supports absent station targets.
Existing station targets in V1 packages remain unchanged.

Unified source preparation now supports selected source families in one
anchor/year package with matching prepared contexts and absent targets. It uses
existing adapters and checkpoint recovery. See [unified preparation](docs/multi-source-preparation.md).
Live integrated and multi-anchor/year acceptance remain pending.

The unified preparation command also accepts user-defined inclusive UTC start/end
dates. It retrieves the requested interval instead of first downloading a full
year. MODIS retains composite-start selection and original composite support.
See [date-range behavior](docs/multi-source-preparation.md#user-defined-dates).

A one-month live GEE run now passes through unified preparation and delivery;
see [online evidence](docs/period-online-validation.json). Sentinel-1 had no
matching acquisitions in this case, and Aqua LST was partial. Contexts were reused.

Sentinel-1 now also passes a separate month with 11 real acquisitions, including
download, 50 m processing, NetCDF delivery and offline reuse. See
[Sentinel-1 online evidence](docs/sentinel1-online-validation.json).

Python environment selection is explicit and persisted locally. The agent uses
[environment diagnosis and launch](docs/python-environment.md) so later sessions
and interrupted tasks keep the same interpreter without relying on shell activation.
