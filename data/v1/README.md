# V1 catalogue

This directory contains the V1 release metadata and compressed CSV catalogue,
copied from the completed benchmark release. Annual ZIP packages are not in GitHub.
Their hosting address is not yet configured; `download_base_url` is therefore null.

Included files:

- `release.json`: release identity, coverage summary and data download entry point.
- `catalog.csv.gz`: 19,982 anchor-year package records, source
  availability, package sizes, SHA-256 hashes and download references.

Station-inventory anchors and anchors with delivered packages are distinct counts.
Catalogue references must not depend on private development paths or credentials.
The original v1 `anchor_count` field remains 1,679. Explicit
`package_anchor_count` (1,679) and `station_inventory_anchor_count` (1,822) clarify
the distinction without changing catalogue records. The inventory itself is not
included in this catalogue. The compressed catalogue is byte-identical to v1;
its SHA-256 and module migration origins are recorded in `docs/migration-provenance.json`.
