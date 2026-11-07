# Soil Moisture Benchmark Agent

An agent-assisted workflow for extending the Global Soil Moisture Benchmark to
user-specified locations, periods and registered data sources.

> **Development preview for external testing; not a stable release.**
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
> configuration one step at a time, and ask what location and dates I need.

> 请阅读 AGENTS.md 和 skills/extend-soil-moisture-benchmark/SKILL.md。
> 帮我开始使用：检查环境，逐步引导必要的配置，再询问我要处理的地点和起止日期。

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

See copy-and-paste usage examples in [English](docs/usage-examples.md) or
[简体中文](docs/usage-examples.zh-CN.md) for first-time setup,
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

**Development preview, ready for external testing.** The repository implements
source preparation and delivery through maintained Python tools, coordinated by
shared agent instructions and source-specific skills.

### Implemented

- Twelve source adapters: SRTM, HWSD2, MCD12Q1, GLDAS, ERA5-Land, IMERG,
  separate Terra/Aqua NDVI and LST, Sentinel-1, and SMAP L4 v007.
- Unified multi-source preparation for one anchor cell and a date range within
  one year, with matching prepared contexts and absent station targets.
  Inclusive UTC start/end dates are honored; full-year requests remain supported.
  MODIS selects composite start dates and retains original composite support.
- Source-specific checkpoints, bounded retries, output validation and one ZIP
  containing selected inputs, context assets, provenance and explicit source gaps.
- Offline V1 catalogue lookup and verified local ZIP reuse. Python environment
  selection, dependency diagnosis and launch through a recorded interpreter path.

See [usage examples](docs/usage-examples.md),
[unified preparation](docs/multi-source-preparation.md), and
[Python environment handling](docs/python-environment.md).

### Verified

- Offline source tests and V1 replay checks, plus a live GLDAS cell/year test.
- One integrated April 2015 package at `EASE2_M09km_R0169_C1995`: all nine
  dynamic sources available, including 11 Sentinel-1 acquisitions. Eight sources
  were retrieved online; previously live-downloaded Sentinel-1 and V1 contexts
  were reused. Source validation, relocated archive checks and network-blocked
  source/cache reuse passed. Ancillary nulls remain explicit. See
  [monthly acceptance evidence](docs/full-month-online-validation.json).

These results validate the recorded cases, not every location, platform or agent
model. Historical validation files retain their original code versions and scope.

### Remaining limits

- Fresh-environment installation, live context acquisition and a fully new-location
  workflow including context preparation still need acceptance.
- Kimi has a discovery entry and setup instructions, but no Kimi model session
  has been validated. Tool-level tests are not cross-model behavioral evidence.
- Multi-anchor/year batch scheduling is not implemented. The agent splits
  cross-year date requests into per-year segments with matching contexts.
- SMAP v007 live retrieval has passed for one month; equivalence of its legacy
  GEE geographic sampling to original NAS/EASE native-cell values remains unverified.
- Station-data ingestion, including private observations, is outside current scope.
- The external V1 download endpoint is not configured. Catalogue entries alone
  do not provide remote package retrieval.

See [implementation details](docs/implementation.md) for the remaining acceptance
work. This is not yet a stable release or a claim that all manuscript workflow
validation has been completed.

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

Station-data ingestion is outside the current extension scope. Existing station
targets in V1 packages remain unchanged. New preparation packages contain inputs
and metadata with station targets explicitly absent.
