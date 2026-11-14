# SMAP L3 integration acceptance — 14 November 2026

Release version: `0.2.0.dev0` (development preview).

## Scope

SMAP L3 is the thirteenth registered source adapter. It uses the existing
`SourceUnit -> plan -> prepare -> validate` interface and unified package
assembler. The coordinator/source index, Earthdata onboarding, dependency
diagnosis and source skill are included in this checkout. SMAP L4's GEE route
and scientific profile are unchanged. New arbitrary products still require
reviewed code, profiles, tests and registration.

The decoder, bounded Harmony acquisition, credential checker and explicit ZIP
merge were migrated from the earlier local standalone prototype. The separate
prototype is not a runtime dependency. All imports use `sm_benchmark_agent`.
The integrated adapter adds exact-period availability, field-null reporting,
native-cell/time/schema validation and short physical cache paths for Windows.

## Verified

- Full repository regression suite: 98 tests passed.
- Built and installed `sm_benchmark_agent-0.2.0.dev0` into an isolated target
  directory, using the existing scientific interpreter/dependencies. Nine L3
  decoder, provider, adapter and merge tests passed against installed modules.
- Source-index/entrypoint consistency, offline planning and selected dependencies
  were checked. Updated source/coordinator skill frontmatter validated.
- Synthetic integrated tests include L3 with all other registered dynamic
  sources for a full-year scope and an exact April 2015 scope. Failure/resume,
  source checkpoints, unchanged values, one-ZIP assembly and relocation pass.
- Network-blocked replay used the actual previously downloaded L3 granule for
  EASE2_M09km_R0333_C0792 on 31 March 2015, with V1 ERA5 and static/annual contexts.
  One unified date-scoped ZIP was produced. Both AM/PM records retained exact
  values, timestamps and masks. Cache/output reuse and relocated ZIP checks pass.
  ERA5 provider IDs were reconstructed from timestamps for replay only.
- The actual existing station-bearing 2015 package was also augmented through
  the explicit merge route. Original targets and other source inputs were
  preserved; partial L3 coverage remained explicit and the base was not replaced.

## Limits

The replay is not a new online download from this checkout, fresh-environment
installation, new-location context acquisition or a coding-agent model trial.
The original decoder/provider route had one live cell/day acceptance; this does
not demonstrate global completeness. Provider errors/uncertain jobs stop rather
than becoming scientific absence. Multi-anchor scheduling and automatic global
catalogue rebuilding remain outside this release. The unified route still
requires matching prepared contexts and absent station targets; the explicit
merge route preserves targets from an existing benchmark ZIP.

An existing GDAL_DATA/gdalvrt.xsd warning was observed during tests. Raster
validation and the suite passed; no global GDAL settings were changed to hide it.
