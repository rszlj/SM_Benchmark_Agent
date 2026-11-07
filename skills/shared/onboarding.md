# Shared onboarding and provider configuration

Use this when the user says "help me start", when dependencies are missing, or
when an authorized route needs provider access. Use the user's language; expose
only the next necessary human action. Do not give beginners a shell-command
checklist or require them to edit JSON/TOML themselves.

1. Follow the [Python environment contract](../../docs/python-environment.md).
   Locate a bootstrap Python 3.11+, then use `scripts/python_env.py` to select and
   diagnose the scientific interpreter. Priority is explicit user path, saved
   checkout-local selection, `.venv`, then `.conda`; never silently fall back to
   PATH. Save the choice only in ignored `.local/python-environment.json`.
   If absent, help create a project environment; prefer the Conda specification
   for native GDAL. Run dependency checks for the selected sources before work.
   Use the selected absolute interpreter for pip, commands, tests and recovery,
   including new sessions; shell activation is not the source of truth. Launch
   registered commands through the bootstrap's `run` action. A stale path or
   changed version/prefix requires diagnosis and explicit reselection. Install
   only needed extras; do not claim fresh-environment acceptance from an import
   check or modify global Python/GDAL paths to hide a failure.
2. Create private request files from the relevant `configs/` examples under an
   ignored location such as `.tmp/`. Keep user requests/configuration out of public
   examples. Recover existing requirements and configuration references first.
3. Start with offline catalogue planning. No provider login is needed for planning,
   verified local reuse or processing already cached inputs. Missing hosting URLs
   are unresolved access, not working download links.
4. For authorized GEE work, follow [the setup reference](../../docs/setup.md#configure-google-earth-engine-gee).
   Distinguish official account login, an authorized registered Cloud project,
   and the request's configuration-file reference. Account registration, provider
   terms and browser sign-in remain human actions. Explain them one step at a time.
5. Reuse an existing configuration path or ask for the authorized project ID and
   write an ignored private configuration. Use the documented JSON format or TOML
   `[gee]` table with `project` and optional `auth_mode = "interactive"`. The current
   routes use existing official interactive login; do not substitute other auth
   modes. This label is not the official CLI's `--auth_mode` argument.
6. Guide official `earthengine authenticate` only when login is needed. Do not ask
   for tokens, private keys or the contents of the OAuth credential file. Never
   read/display that credential file to diagnose login. Use the selected config
   in place through `credential_ref`; do not duplicate it. Relative paths resolve
   from the working directory. `gee.env`, OAuth files and GitHub tokens are not
   substitutes for the project configuration.
7. A requested connectivity check is online; do not run it during plan-only work.
   Successful authentication proves neither source coverage nor correctness.
   Keep source-specific live acceptance distinct from login and offline tests.

Routine local setup follows a request to get started. It does not authorize
unbounded downloads, account registration, acceptance of terms or changed science.
Reuse existing authorization; do not ask again merely because a different skill
was loaded. HWSD2's source skill handles its separate non-GEE global-cache scope.
