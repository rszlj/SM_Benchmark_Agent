"""Annual Terra MOD13Q1 NDVI stacks from NAS or targeted GEE gap filling."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from ..grid import ContextGrid
from .srtm import _expanded_wgs84_bounds


MOD13Q1_COLLECTION = "MODIS/061/MOD13Q1"
MOD13Q1_NDVI_SNAPSHOT_ID = "nas-20260805"
MOD13Q1_NDVI_SCALE = 0.0001
MOD13Q1_NDVI_VALID_MIN = -2000
MOD13Q1_NDVI_VALID_MAX = 10000
MOD13Q1_NDVI_RAW_NODATA = -3000
MOD13Q1_NDVI_OUTPUT_NODATA = -9999.0
DATE_PREFIX = re.compile(r"^(\d{4})_(\d{2})_(\d{2})")


def _validate_context(context: ContextGrid) -> None:
    if (
        context.nominal_resolution != "250 m"
        or context.rows != 52
        or context.columns != 52
    ):
        raise ValueError(
            "MOD13Q1 NDVI output requires ContextResolution('250 m', 4)"
        )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mod13q1_ndvi_output_paths(
    output_root: str | Path,
    snapshot_id: str,
    anchor_id: str,
    year: int,
) -> tuple[Path, Path]:
    directory = (
        Path(output_root)
        / "derived"
        / "mod13q1_ndvi"
        / snapshot_id
        / anchor_id
        / f"{year:04d}"
    )
    target = directory / f"mod13q1_ndvi_{year:04d}_16day_250m_EPSG6933.tif"
    return target, target.with_suffix(target.suffix + ".manifest.json")


def dates_from_descriptions(descriptions: tuple[str | None, ...]) -> list[date]:
    dates = []
    for description in descriptions:
        match = DATE_PREFIX.match(description or "")
        if match is None:
            raise ValueError(f"cannot parse MOD13Q1 date from band: {description!r}")
        dates.append(date(*(int(value) for value in match.groups())))
    if dates != sorted(set(dates)):
        raise ValueError("MOD13Q1 band dates must be unique and chronological")
    return dates


def derive_mod13q1_ndvi_bytes(
    *,
    payload: bytes,
    target: str | Path,
    context: ContextGrid,
    dates: list[date] | None = None,
    provenance: dict[str, object],
    platform: str = "Terra",
    source_crs_override: str | None = None,
) -> dict[str, object]:
    """Scale and reproject one annual WGS84/native NDVI stack to EASE2."""

    import numpy
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject

    _validate_context(context)
    if platform not in {"Terra", "Aqua"}:
        raise ValueError("platform must be Terra or Aqua")
    collection_id = MOD13Q1_COLLECTION if platform == "Terra" else "MODIS/061/MYD13Q1"
    target_path = Path(target)
    manifest = target_path.with_suffix(target_path.suffix + ".manifest.json")
    if target_path.exists() and manifest.exists():
        return {"status": "existing", "target": str(target_path)}
    if manifest.exists() and not target_path.exists():
        raise FileExistsError(f"manifest exists without raster: {manifest}")

    with MemoryFile(payload) as memory:
        with memory.open() as source:
            source_dates = dates or dates_from_descriptions(source.descriptions)
            if len(source_dates) != source.count:
                raise ValueError("MOD13Q1 dates do not match source band count")
            if any(item.year != source_dates[0].year for item in source_dates):
                raise ValueError("MOD13Q1 stack crosses calendar years")
            if source.crs is None:
                raise ValueError("MOD13Q1 source has no CRS")
            destination_transform = from_origin(
                context.upper_left_x_m,
                context.upper_left_y_m,
                context.exact_spacing_m,
                context.exact_spacing_m,
            )
            profile = {
                "driver": "GTiff",
                "width": context.columns,
                "height": context.rows,
                "count": source.count,
                "dtype": "float32",
                "crs": f"EPSG:{context.crs_epsg}",
                "transform": destination_transform,
                "nodata": MOD13Q1_NDVI_OUTPUT_NODATA,
                "compress": "deflate",
                "predictor": 3,
                "tiled": True,
                "blockxsize": 256,
                "blockysize": 256,
                "interleave": "band",
            }
            target_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = target_path.with_suffix(target_path.suffix + ".part")
            try:
                with rasterio.open(temporary, "w", **profile) as output:
                    for band_index, composite_date in enumerate(source_dates, start=1):
                        values = source.read(band_index).astype("float32")
                        invalid = (
                            ~numpy.isfinite(values)
                            | (values < MOD13Q1_NDVI_VALID_MIN)
                            | (values > MOD13Q1_NDVI_VALID_MAX)
                        )
                        values[~invalid] *= MOD13Q1_NDVI_SCALE
                        values[invalid] = MOD13Q1_NDVI_OUTPUT_NODATA
                        destination = numpy.full(
                            (context.rows, context.columns),
                            MOD13Q1_NDVI_OUTPUT_NODATA,
                            dtype="float32",
                        )
                        reproject(
                            source=values,
                            destination=destination,
                            src_transform=source.transform,
                            # GEE may serialize SR-ORG:6974 with a WGS84
                            # ellipsoid WKT even though the pixel transform is
                            # on the MODIS authalic sphere. Aqua downloads pass
                            # the authoritative MODIS sinusoidal definition.
                            src_crs=source_crs_override or source.crs,
                            src_nodata=MOD13Q1_NDVI_OUTPUT_NODATA,
                            dst_transform=destination_transform,
                            dst_crs=f"EPSG:{context.crs_epsg}",
                            dst_nodata=MOD13Q1_NDVI_OUTPUT_NODATA,
                            resampling=Resampling.bilinear,
                        )
                        output.write(destination, band_index)
                        output.set_band_description(
                            band_index, f"{composite_date.isoformat()}_{platform}"
                        )
                        output.update_tags(
                            band_index,
                            timestamp_utc=datetime.combine(
                                composite_date, datetime.min.time(), timezone.utc
                            ).isoformat(),
                            platform=platform,
                            source_scale_factor_applied=str(MOD13Q1_NDVI_SCALE),
                        )
                    output.update_tags(
                        collection=collection_id,
                        variable="NDVI",
                        temporal_sampling="16-day composite",
                        resampling="bilinear",
                    )
                os.replace(temporary, target_path)
            finally:
                if temporary.exists():
                    temporary.unlink()

    metadata = {
        "availability": "available",
        "collection": collection_id,
        "platform": platform,
        "year": source_dates[0].year,
        "anchor_id": context.anchor_id,
        "composite_dates": [item.isoformat() for item in source_dates],
        "bands": len(source_dates),
        "scale_factor_applied": MOD13Q1_NDVI_SCALE,
        "valid_raw_range": [MOD13Q1_NDVI_VALID_MIN, MOD13Q1_NDVI_VALID_MAX],
        "target_grid": {
            "crs_epsg": context.crs_epsg,
            "rows": context.rows,
            "columns": context.columns,
            "exact_spacing_m": context.exact_spacing_m,
            "upper_left_x_m": context.upper_left_x_m,
            "upper_left_y_m": context.upper_left_y_m,
        },
        "output": {"file": str(target_path), "sha256": _sha256_file(target_path)},
        "source": {"sha256": _sha256_bytes(payload), **provenance},
    }
    if source_crs_override is not None:
        metadata["source_crs_override"] = source_crs_override
    temporary_manifest = manifest.with_suffix(manifest.suffix + ".part")
    temporary_manifest.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest)
    return {"status": "derived", "target": str(target_path), "manifest": str(manifest)}


