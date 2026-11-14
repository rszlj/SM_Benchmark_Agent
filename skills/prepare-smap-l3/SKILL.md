---
name: prepare-smap-l3
description: Prepare SMAP enhanced L3 V006 soil moisture and H/V brightness temperature through Earthdata Harmony, validate native-cell AM/PM records, and include them in unified benchmark delivery.
---

# SMAP L3 native-cell inputs

Use source `smap_l3`, profile `smap-l3-enhanced-v006-native-am-pm-tb-v1`.
Read [shared execution](../shared/execution.md), and [onboarding](../shared/onboarding.md)
when needed. Follow the [source guide](../../docs/smap-l3-preparation.md).

Use `sm-benchmark-prepare` with the same exact dates and reviewed context plan
as other sources. The adapter uses Earthdata, not GEE; users do not need to run
a second preparation workflow. The coordinator assembles one package after the
selected sources have been validated. Do not expand a month to a year silently.

Preserve V006, both AM/PM passes, native EASE cell identity, soil moisture and
corrected/uncorrected H/V TB with provider flags. Uncorrected TB has native
36 km support despite the 9 km posted grid. Convert source TDB time to UTC with
the registered decoder. Missing values remain null, not zero or interpolated.
No extra quality screening is imposed; provider flags remain available to users.

Earthdata credentials stay in the user's home `.netrc`. Never put passwords,
job IDs, signed download URLs or GEE project IDs in public metadata. Persist
private Harmony checkpoints. Uncertain submissions and failed remote jobs stop
for review; do not automatically submit duplicates or switch accounts. Polling
is bounded and can resume. This route currently accepts completed calendar years.

To augment an existing station-bearing benchmark ZIP, use the guide's explicit
merge route after preparing matching annual L3 assets. Preserve targets and other
inputs, write a new package, and report partial coverage. Do not overwrite V1 or
confuse this route with ingestion of new station observations.

Return source availability, missing dates/null counts, output paths and actual
acceptance evidence. Source start is 31 March 2015; coverage before that is
unavailable, not a download failure. Adding future sources still requires a
reviewed adapter, profile, validation and source-index entry, not prose alone.
