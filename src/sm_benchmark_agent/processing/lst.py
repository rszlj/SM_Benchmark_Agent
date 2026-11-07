"""Compact Terra MOD11A2 day/night LST stacks for benchmark anchors."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from ..grid import ContextGrid
from .landcover import NATIVE_CRS as MODIS_SINUSOIDAL_CRS
from .srtm import _gdal_module


MOD11A2_LST_COLLECTION = "MODIS/061/MOD11A2"
MOD11A2_LST_SNAPSHOT_ID = "gee-20260806"
MOD11A2_LST_CHUNKS = (
    ("2000_2007", "2000-01-01", "2008-01-01"),
    ("2008_2015", "2008-01-01", "2016-01-01"),
    ("2016_2025", "2016-01-01", "2026-01-01"),
)
MYD11A2_LST_CHUNKS = (
    ("2002_2007", "2002-01-01", "2008-01-01"),
    ("2008_2015", "2008-01-01", "2016-01-01"),
    ("2016_2025", "2016-01-01", "2026-01-01"),
)
MOD11A2_LST_RAW_NODATA = -32768
MOD11A2_LST_VALID_RAW_MIN = 7500
MOD11A2_LST_VALID_RAW_MAX = 32767
MOD11A2_LST_OUTPUT_NODATA = -9999.0
MOD11A2_LST_SCALE = 0.02
MOD11A2_LST_CELSIUS_OFFSET = -273.15


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_context(context: ContextGrid) -> None:
    if (
        context.nominal_resolution != "1 km"
        or context.rows != 13
        or context.columns != 13
    ):
        raise ValueError(
            "MOD11A2 LST output requires ContextResolution('1 km', 1)"
        )


def mod11a2_lst_output_paths(
    output_root: str | Path, snapshot_id: str, anchor_id: str, product: str = "mod11a2"
) -> tuple[Path, Path, Path]:
    if product not in {"mod11a2", "myd11a2"}:
        raise ValueError("Unsupported LST product")
    period = "2000_2025" if product == "mod11a2" else "2002_2025"
    directory = (
        Path(output_root)
        / "derived"
        / f"{product}_lst"
        / snapshot_id
        / anchor_id
    )
    day = directory / f"{product}_lst_day_{period}_8day_1km_EPSG6933.tif"
    night = directory / f"{product}_lst_night_{period}_8day_1km_EPSG6933.tif"
    return day, night, directory / f"{product}_lst_{period}.manifest.json"


def derive_mod11a2_lst(
    *,
    raw_chunks: dict[str, str | Path],
    dates_by_chunk: dict[str, list[str]],
    context: ContextGrid,
    output_root: str | Path,
    snapshot_id: str = MOD11A2_LST_SNAPSHOT_ID,
    source_provenance: dict[str, dict[str, object]] | None = None,
    source_crs: str | None = MODIS_SINUSOIDAL_CRS,
    working_root: str | Path | None = None,
    product: str = "mod11a2",
    year: int | None = None,
    tile_directory: str | Path | None = None,
) -> dict[str, object]:
    """Reproject paired raw day/night chunks into two compact Celsius stacks."""

    import numpy
    import rasterio
    from rasterio.transform import from_origin

    _validate_context(context)
    day, night, manifest = mod11a2_lst_output_paths(
        output_root, snapshot_id, context.anchor_id, product
    )
    if year is not None:
        directory = Path(tile_directory) if tile_directory is not None else Path(output_root)
        day = directory / f"{product}_lst_day_{year}_8day_1km_EPSG6933.tif"
        night = directory / f"{product}_lst_night_{year}_8day_1km_EPSG6933.tif"
        manifest = directory / f"{product}_lst_{year}.manifest.json"
    platform = "Terra" if product == "mod11a2" else "Aqua"
    collection = f"MODIS/061/{product.upper()}"
    chunk_plan = MOD11A2_LST_CHUNKS if product == "mod11a2" else MYD11A2_LST_CHUNKS
    outputs = (day, night, manifest)
    if all(path.exists() for path in outputs):
        return {"status": "existing", "day": str(day), "night": str(night)}
    if any(path.exists() for path in outputs):
        raise FileExistsError("partial immutable MOD11A2 LST output exists")
    ordered_chunks = sorted(raw_chunks) if year is not None else [item[0] for item in chunk_plan if item[0] in raw_chunks]
    if set(ordered_chunks) != set(raw_chunks) or not ordered_chunks:
        raise ValueError("raw_chunks contain unknown or no chunk identifiers")
    all_dates = [date for chunk in ordered_chunks for date in dates_by_chunk[chunk]]
    if all_dates != sorted(set(all_dates)):
        raise ValueError("MOD11A2 dates must be unique and chronological")
    if year is not None and any(not stamp.startswith(f'{year:04d}-') for stamp in all_dates):
        raise ValueError('Annual LST chunks must belong to the selected year')

    day.parent.mkdir(parents=True, exist_ok=True)
    scratch_parent = Path(working_root) if working_root else day.parent / ".tmp"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    gdal = _gdal_module()
    temporary_day = day.with_suffix(day.suffix + ".part")
    temporary_night = night.with_suffix(night.suffix + ".part")
    created: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix="mod11a2-lst-", dir=scratch_parent) as directory:
            scratch = Path(directory)
            warped: dict[tuple[str, str], Path] = {}
            for chunk in ordered_chunks:
                source = Path(raw_chunks[chunk])
                dataset = gdal.Open(str(source), gdal.GA_ReadOnly)
                expected = 2 * len(dates_by_chunk[chunk])
                if dataset is None or dataset.RasterCount != expected:
                    raise ValueError(
                        f"raw MOD11A2 chunk {chunk} must contain {expected} bands"
                    )
                dataset = None
                for slot, first_band in (("day", 1), ("night", 2)):
                    target = scratch / f"{chunk}_{slot}.tif"
                    result = gdal.Warp(
                        str(target),
                        str(source),
                        options=gdal.WarpOptions(
                            format="GTiff",
                            srcBands=list(range(first_band, expected + 1, 2)),
                            outputBounds=(
                                context.bounds.xmin,
                                context.bounds.ymin,
                                context.bounds.xmax,
                                context.bounds.ymax,
                            ),
                            width=context.columns,
                            height=context.rows,
                            srcSRS=source_crs,
                            dstSRS=f"EPSG:{context.crs_epsg}",
                            outputType=gdal.GDT_Float32,
                            srcNodata=MOD11A2_LST_RAW_NODATA,
                            dstNodata=MOD11A2_LST_RAW_NODATA,
                            resampleAlg="bilinear",
                            # Every date has its own clear-sky mask. Do not let
                            # validity in one band make another band's fill
                            # pixels participate in bilinear interpolation.
                            warpOptions=["UNIFIED_SRC_NODATA=NO"],
                            creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
                        ),
                    )
                    if result is None:
                        raise RuntimeError(f"GDAL failed to warp {chunk} {slot}")
                    result = None
                    warped[(chunk, slot)] = target

            profile = {
                "driver": "GTiff",
                "width": context.columns,
                "height": context.rows,
                "count": len(all_dates),
                "dtype": "float32",
                "crs": f"EPSG:{context.crs_epsg}",
                "transform": from_origin(
                    context.upper_left_x_m,
                    context.upper_left_y_m,
                    context.exact_spacing_m,
                    context.exact_spacing_m,
                ),
                "nodata": MOD11A2_LST_OUTPUT_NODATA,
                "compress": "deflate",
                "predictor": 3,
                "tiled": True,
                "blockxsize": 256,
                "blockysize": 256,
                "interleave": "band",
            }
            with rasterio.open(temporary_day, "w", **profile) as day_output, rasterio.open(
                temporary_night, "w", **profile
            ) as night_output:
                offset = 0
                for chunk in ordered_chunks:
                    dates = dates_by_chunk[chunk]
                    indexes = list(range(offset + 1, offset + len(dates) + 1))
                    for slot, output in (("day", day_output), ("night", night_output)):
                        with rasterio.open(warped[(chunk, slot)]) as source:
                            values = source.read().astype("float32")
                        # The GEE GeoTIFF uses a signed fill value. Near masked
                        # edges, warping can produce values infinitesimally above
                        # that fill code, so equality alone is insufficient.
                        invalid = (
                            (values < MOD11A2_LST_VALID_RAW_MIN)
                            | (values > MOD11A2_LST_VALID_RAW_MAX)
                        )
                        values[~invalid] = (
                            values[~invalid] * MOD11A2_LST_SCALE
                            + MOD11A2_LST_CELSIUS_OFFSET
                        )
                        values[invalid] = MOD11A2_LST_OUTPUT_NODATA
                        output.write(values, indexes=indexes)
                        for band_index, date in zip(indexes, dates):
                            output.set_band_description(band_index, date)
                            output.update_tags(
                                band_index,
                                composite_start=date,
                                platform=platform,
                                variable=f"LST_{slot.title()}_1km",
                                unit="degree Celsius",
                            )
                    offset += len(dates)
                for slot, output in (("day", day_output), ("night", night_output)):
                    output.update_tags(
                        collection=collection,
                        platform=platform,
                        variable=f"LST_{slot.title()}_1km",
                        temporal_sampling="8-day composite",
                        unit="degree Celsius",
                        source_scale=str(MOD11A2_LST_SCALE),
                        source_offset=str(MOD11A2_LST_CELSIUS_OFFSET),
                        resampling="bilinear",
                    )
        os.replace(temporary_day, day)
        created.append(day)
        os.replace(temporary_night, night)
        created.append(night)

        provenance = source_provenance or {}
        metadata = {
            "availability": "available",
            "collection": collection,
            "platform": platform,
            "anchor_id": context.anchor_id,
            "snapshot_id": snapshot_id,
            "dates": all_dates,
            "composite_count": len(all_dates),
            "variables": ["LST_Day_1km", "LST_Night_1km"],
            "unit": "degree Celsius",
            "source_transform": {
                "scale": MOD11A2_LST_SCALE,
                "offset": MOD11A2_LST_CELSIUS_OFFSET,
                "valid_raw_range": [
                    MOD11A2_LST_VALID_RAW_MIN,
                    MOD11A2_LST_VALID_RAW_MAX,
                ],
            },
            "target_grid": {
                "crs_epsg": context.crs_epsg,
                "rows": context.rows,
                "columns": context.columns,
                "exact_spacing_m": context.exact_spacing_m,
                "upper_left_x_m": context.upper_left_x_m,
                "upper_left_y_m": context.upper_left_y_m,
            },
            "resampling": "bilinear",
            "raw_chunks": {
                chunk: {
                    "file": str(Path(raw_chunks[chunk])),
                    **provenance.get(chunk, {}),
                }
                for chunk in ordered_chunks
            },
            "outputs": {
                "day": {"file": str(day), "sha256": _sha256(day)},
                "night": {"file": str(night), "sha256": _sha256(night)},
            },
            "caution": (
                f"LST is the {product.upper()} eight-day clear-sky composite. Missing clear-sky "
                "retrievals remain nodata; no temporal filling or QC filtering is applied."
            ),
        }
        temporary_manifest = manifest.with_suffix(manifest.suffix + ".part")
        temporary_manifest.write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary_manifest, manifest)
    except Exception:
        for path in (*created, temporary_day, temporary_night):
            if path.exists():
                path.unlink()
        raise
    return {
        "status": "derived",
        "day": str(day),
        "night": str(night),
        "manifest": str(manifest),
    }
