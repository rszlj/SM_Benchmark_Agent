# V1 catalogue

This directory is reserved for the V1 release metadata and catalogue. The files
have not yet been added. Annual ZIP packages are hosted separately, not in GitHub.

Planned files:

- `release.json`: release identity, coverage summary and data download entry point.
- `catalog.parquet` and/or `catalog.csv.gz`: anchor-year package index, source
  availability, package sizes, SHA-256 hashes and download references.

Station-inventory anchors and anchors with delivered packages are distinct counts.
Catalogue references must not depend on private development paths or credentials.
