# Python environment selection and recovery

The agent handles these steps. Users describe their task and any existing Python
environment they want to use; they do not need to activate terminals or edit paths.
The bootstrap is `scripts/python_env.py`, uses the standard library, and locates
the checkout from its own file rather than the terminal working directory.
Running the bootstrap itself requires an available Python 3.11+ interpreter.
If none exists, guide installation before attempting benchmark commands.

## Selection contract

1. Explicit `--python PATH` wins. Relative paths resolve against the checkout.
2. Otherwise use `.local/python-environment.json`, bound to this checkout.
3. Without a saved record, try `.venv`, then `.conda` inside the checkout.
4. Otherwise stop and create or select an environment. Do not silently use PATH,
   another repository's environment, or whichever shell happened to be active.

Windows interpreter paths are `.venv/Scripts/python.exe` and `.conda/python.exe`;
on Linux/macOS they are `.venv/bin/python` and `.conda/bin/python`. Preserve venv
symlink paths rather than resolving them to the base interpreter.
The ignored local record contains the absolute interpreter path, checkout root,
Python version and prefix. It contains no credentials and must not enter Git.
A missing interpreter or relocated checkout requires explicit reselection. Every
run probes again; a saved version/prefix change requires check and reselection.

`check` does not save a choice. `select` saves a supported Python even if some
dependencies are missing, returning exit code 2 until dependency checks pass.
This allows installation to target the selected interpreter. Never interpret a
nonzero dependency check as a ready environment.

## Create the environment

For the full scientific workflow, prefer the Conda specification with native GDAL.
From the checkout root, after locating the actual Conda executable:

```text
conda env create --prefix ./.conda --file environment.yml
```

Do not replace an existing environment to fix a failed solve. Diagnose the
reported dependency conflict. The specification is a tested-development version
set, not a universal platform lockfile; a clean solve still needs acceptance on
the user's platform. Native GDAL must match its Python bindings. Avoid combining
unrelated GDAL DLLs or setting global GDAL_DATA/PROJ paths as a workaround.

For catalogue-only or appropriately limited work, a `.venv` can be sufficient.
Create it using the selected bootstrap Python, then install with the new
interpreter's absolute path and `-m pip install -e .` plus the selected extras.
Use `environment.yml` for workflows requiring native GDAL instead of assuming
that pip alone supplies a working native stack on every platform.

## Bind, diagnose and run without shell activation

PowerShell examples for the agent, from the checkout root:

```powershell
& ./.conda/python.exe scripts/python_env.py select --python .conda/python.exe --extras all
& ./.conda/python.exe scripts/python_env.py check --extras all
& ./.conda/python.exe scripts/python_env.py run --command sm-benchmark-prepare --extras contexts,timeseries -- --request .tmp/request.json --context-plan .tmp/context.json --asset-root cache/sources
```

After discovery, substitute the selected **absolute** interpreter path into every
command, using PowerShell's `&` and quoting paths that contain spaces. The launcher
uses argument arrays rather than shell interpolation. It runs the current
checkout's registered command modules in that interpreter, with isolation from
ambient PYTHONPATH/user-site settings; an editable installation is not required
merely to locate this checkout's modules. Dependencies must still be installed.

Only command names registered in `pyproject.toml` can be launched. `--` separates
bootstrap options from workflow arguments. The selected extra groups are checked
before launch; unified preparation defaults to all groups. An agent can narrow
`--extras` to the union required by selected sources and context validation.
For `sm-benchmark-agent --workflow gldas`, explicitly include `--extras gldas`.

Dependency diagnosis imports the selected modules, checks EPSG:6933 through
PyProj/Rasterio, and creates a GDAL memory dataset when GDAL is required. It does
not authenticate, download data, read OAuth files, or prove provider access.
Import warnings are reported as a flag; missing/broken imports as exception types.
Warnings need assessment, not automatic global environment modification.

Use the same Python for `-m pip`, tests, preparation and recovery. Earth Engine's
login executable must come from that same environment (`Scripts/earthengine.exe`
on Windows, `bin/earthengine` on Unix), after its dependencies are installed.
Model-host software such as Kimi CLI is separate from the scientific environment.

## Verification limits

Tests cover explicit/saved/local precedence, missing paths, relocated checkouts,
paths containing spaces, selected-interpreter probing and launching from outside
the checkout. Full dependency diagnosis is exercised in the existing scientific
environment. This does not establish a fresh Conda solve or Kimi model behavior.
