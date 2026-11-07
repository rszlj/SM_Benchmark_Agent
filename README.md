# Soil Moisture Benchmark Agent

An agent-assisted workflow for extending the Global Soil Moisture Benchmark to
user-specified locations, periods and registered data sources.

## Status

This repository currently contains the initial project structure. The extension
agent and its source adapters are under development; no runnable release is
provided yet.

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
