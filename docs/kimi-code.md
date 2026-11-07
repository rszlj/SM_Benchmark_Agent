# Using the benchmark with Kimi Code

## Entry and setup

Open the complete checkout in a Kimi Code environment that can read local files
and run project commands. Send the same beginner prompt from the
[README](../README.md#start-with-your-coding-agent). The agent should guide Python,
dependencies and GEE setup through the shared onboarding instructions. Kimi model
authentication and GEE authentication are separate; neither belongs in repository
examples or public data packages.

Kimi documents project `AGENTS.md` instructions. This repository already uses
that entry, so it needs no separate `KIMI.md` or custom system prompt.
See [official instruction-file support](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/agents#instruction-files).

The current documented project skill locations include `.agents/skills/`.
Our [sm-benchmark entry](../.agents/skills/sm-benchmark/SKILL.md) lives there and
routes to the existing coordinator in `skills/`. It contains no duplicate science
or processing code. Where skill discovery is supported, invoke `/skill:sm-benchmark`.
See [official skill discovery](https://moonshotai.github.io/kimi-code/en/customization/skills).

For a CLI version supporting explicit skill directories, an alternative from the
repository root is:

```powershell
kimi --skills-dir ./skills
```

Then use `/skill:extend-soil-moisture-benchmark`. This option replaces automatic
skill-directory discovery for that launch; it is optional, not a prerequisite for
reading the repository's instructions. Verify the installed version's `--help`
if flags differ. See [official command reference](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-command).

A plain Kimi chat without local file and command tools cannot execute this
workflow. If using a Kimi model through another coding host, use that host's
repository-instruction mechanism and record both host and model identities.
The scientific Python tools remain independent of the language-model provider.

## Acceptance status and next check

The discovery entry and local references have been checked. `kimi` was not found
on PATH during the compatibility review on 2026-11-08; no Kimi model session was
run. Existing Python tests and GEE acceptance do not establish Kimi agent behavior.

For the first Kimi session, ask it to read the entry and explain an exact-date,
station-free request without contacting providers. Check that it selects the
correct source skills, uses the unified date-range command and identifies needed
contexts. Then test an authorized cached or bounded online request and recovery.
Record the actual Kimi/host versions, model ID, task, result and sanitized tool
evidence before claiming cross-model acceptance in the manuscript. Do not record
API keys, OAuth files or raw private session logs as public evidence.
