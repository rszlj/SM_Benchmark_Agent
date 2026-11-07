# Skill routing and maintenance

Users enter through [AGENTS.md](../AGENTS.md) and the
[coordinator](../skills/extend-soil-moisture-benchmark/SKILL.md). They do not need
to install or choose individual skills. The files are used directly from the full
repository checkout; copying a single skill folder without its shared references,
guides and code is not a supported standalone distribution.

## Responsibilities

| Layer | Maintained content | When read |
|---|---|---|
| Coordinator | Requirements, catalogue reuse, routing, scope and delivery coordination | Entry to a task |
| [Source index](../skills/source-index.json) | Source ID to skill/profile/workflow mapping; unsupported sources | When source preparation is needed |
| `skills/prepare-*/SKILL.md` | Dataset-specific decisions, pitfalls and handoff | Only for selected sources or missing prerequisites |
| [Shared onboarding](../skills/shared/onboarding.md) | Beginner setup and official provider authentication | When setup is needed |
| [Shared execution rules](../skills/shared/execution.md) | Authorization, checkpoints, scientific invariants and delivery | Once per task |
| Source guides in `docs/` | Exact commands, technical profiles, resource limits and evidence | For the selected workflow |
| Python adapters | Executable processing and validation | Through the documented tools |

There are twelve source skills, one for each implemented adapter. Terra/Aqua NDVI
and day/night LST have separate skill entry points and share the MODIS guide and
processing helpers. SRTM/HWSD2/MCD12Q1 similarly have separate scientific guidance
but share the context command. SMAP L4 has a separate legacy-sampling skill. The index retains ISMN as an unimplemented V1 catalogue identity, outside current migration scope;
no placeholder preparation skill implies a capability that does not exist.

Read index paths from the repository root and Markdown links from the containing
file. The index groups operational commands by workflow, so shared command flags
and dependency groups need not be repeated in every source entry. Do not preload
every source skill or every guide on ordinary startup. A reviewed matching context
can be reused without loading all three context preparation skills.

## Scope is independent of skill layout

The unified command now coordinates selected source adapters. Current preparation
commands accept one anchor/year and absent targets. Context preparation includes
all three context sources. Explain additions before execution and retain the user's
existing scope/authorization. Use [unified preparation](multi-source-preparation.md) for cross-family delivery.
Separate family commands still produce separate packages; do not manually merge them.
Pure catalogue reuse does not require source preparation skills or GEE login.

Example routing checks:

- New user without a location: coordinator and onboarding; recover requirements
  before choosing a source or prompting for GEE.
- Aqua NDVI with reviewed contexts: Aqua NDVI skill and MODIS guide; preserve its
  corrected mask-weight interpolation, without loading Terra or rebuilding contexts.
- HWSD2 only: HWSD2 skill and context guide; explain the CLI bundle and separate
  global-cache scope. HWSD2 itself needs no GEE account.
- ERA5 plus IMERG: two source skills and one shared time-series workflow guide.
- Sentinel-1 plus ERA5: read both source skills, then use the unified workflow
  with matching contexts to produce one package.
- SMAP: disclose legacy geographic sampling and unverified native-cell equivalence.
- User-supplied station data (including private observations): report ingestion
  as unsupported in the current scope; do not assume ISMN format or permission
  to publish. Compatible V1 reuse remains separate; never fabricate observations.

## Adding or changing a source

1. Implement and validate the adapter and its operational route first. Keep
   scientific logic in maintained Python modules, not in skill prose or generated
   per-request code. Record actual acceptance limits in the source guide.
2. Add a focused `skills/prepare-<source>/SKILL.md` with a discriminating description,
   dataset-specific decisions, shared-rule links and a link to its workflow guide.
   Preserve shared algorithms in one guide/module when products are related.
3. Register its source/profile/workflow in `skills/source-index.json`; remove its
   unimplemented entry only when the corresponding adapter exists. Document scope
   additions and prerequisite behavior. Do not expand the coordinator with a new
   source-specific procedural section.
4. Run the skill-creator frontmatter validator on changed skill folders and
   `python -m unittest discover -s tests -p test_skill_routes.py -v` for link,
   registry, entry-point and offline planning checks. Run the relevant scientific
   tests for processing changes. Walk through representative user requests above
   and update cases for a new workflow family.

The structural checks validate routing resources against executable adapters and
entry points. They do not establish that a particular coding-agent model follows
the prose correctly. Independent model sessions, live providers and clean-environment
acceptance remain separate evidence. See [split validation](skill-split-validation.json).

## Coding-host discovery

The optional [sm-benchmark entry](../.agents/skills/sm-benchmark/SKILL.md) in
`.agents/skills/` enables compatible hosts such as Kimi Code to discover the
workflow. It only points to AGENTS.md and the canonical coordinator; source skills
and shared instructions stay under `skills/`. Keep this entry thin and do not copy
source algorithms into it. See [Kimi compatibility](kimi-code.md) for startup and
model-session acceptance limits.
