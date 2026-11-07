# Repository instructions for coding agents

This repository provides an agent-assisted soil moisture benchmark extension
workflow. For onboarding, configuration, data requests and execution, read
`skills/extend-soil-moisture-benchmark/SKILL.md`, then follow its relevant steps.
That coordinator routes through `skills/source-index.json` to individual source
skills. Read only selected source skills and missing prerequisites; shared setup
and execution rules live in `skills/shared/`. For cross-family preparation use the integrated workflow in the source index.
Skill routing does not expand the user's authorized scope.
Read `docs/implementation.md` before promising source or delivery capabilities.
The skill can be read directly from this checkout; a separate installation is
not required. Resolve documentation paths relative to their containing file and
run project commands from the repository root.

## Beginner-facing operation

When the user says "help me start", take responsibility for environment checks,
dependency setup, private configuration and request-file creation. Explain each
necessary human action in the user's language. Ask only for information that
cannot be inferred, and only when needed for the next step. Do not hand the user
a list of shell commands or require them to edit TOML/JSON themselves.

Reuse the current conversation's requirements and authorization. Routine local
setup is part of a request to get started; respect the host's execution permissions.
Do not treat onboarding as permission for arbitrary remote downloads. Present a
concrete bounded data plan and execute within the user's authorized scope, without
repeating approval questions already answered. Provider login, account selection
and acceptance of terms remain with the user.

This is a development checkout, not a completed general multi-source product.
Report missing adapters or inputs plainly. Do not generate new scientific
processing code to make an unsupported request appear supported. Use the
registered tools and preserve explicit scientific choices.

## Repository boundaries

Keep credentials, local environments, downloads, caches and outputs out of Git.
V1 data packages are separate from the GitHub repository; `data/v1` contains
catalogue and release metadata only. Historical production/recovery scripts and
the original developer's workspace are not runtime dependencies.

For code changes, use the relevant tests in `tests/` and describe what was
actually verified. Documentation edits do not establish runtime acceptance.
Do not publish, push, or upload data unless requested.

## Python execution identity

Use [the environment contract](docs/python-environment.md) and
`scripts/python_env.py` for interpreter selection, diagnosis and command launch.
Persist only the private checkout-local selection; use its absolute interpreter
for installs and execution. Missing or stale selections must not silently fall
back to system Python or another project environment.
