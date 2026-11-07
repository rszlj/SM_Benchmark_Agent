"""SRTM download and local GDAL terrain processing."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from urllib.request import urlopen

from pyproj import CRS, Transformer

from ..grid import ContextGrid


GEE_SRTM_IMAGE = "USGS/SRTMGL1_003"
SRTM_SNAPSHOT_ID = "SRTMGL1_003-v3"
SRTM_SOURCE_NODATA = -32768.0
SRTM_OUTPUT_NODATA = -9999.0
SRTM_HALO_M = 120.0
SRTM_WORKING_RESOLUTION_M = 30.0
SRTM_OUTPUT_BANDS = (
    "elevation_m",
    "slope_degrees",
    "aspect_degrees",
    "eastness",
    "northness",
    "aspect_consistency",
)


def _configure_gdal_data() -> None:
    """Supply Conda's GDAL data path when Python is run without activation."""

    gdal_data = Path(sys.prefix) / "Library" / "share" / "gdal"
    if "GDAL_DATA" not in os.environ and gdal_data.is_dir():
        os.environ["GDAL_DATA"] = str(gdal_data)


_configure_gdal_data()


def _gdal_module():
    """Load GDAL and support direct `.conda/python.exe` use without activation."""

    try:
        from osgeo import gdal
    except ImportError as exc:
        raise RuntimeError(
            "Terrain processing requires compatible GDAL Python bindings; see environment.yml"
        ) from exc
    gdal.UseExceptions()
    return gdal


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_context(context: ContextGrid) -> None:
    if (
        context.nominal_resolution != "50 m"
        or context.rows != 260
        or context.columns != 260
    ):
        raise ValueError(
            "SRTM canonical output requires ContextResolution('50 m', 20)"
        )


def compute_slope_aspect_gdal(
    dem: str | Path,
    slope: str | Path,
    aspect: str | Path,
) -> tuple[Path, Path]:
    """Calculate Horn slope and azimuth aspect with GDAL's terrain engine."""

    gdal = _gdal_module()
    dem_path, slope_path, aspect_path = map(Path, (dem, slope, aspect))
    for output in (slope_path, aspect_path):
        if output.exists():
            raise FileExistsError(f"terrain derivative already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
    slope_dataset = gdal.DEMProcessing(
        str(slope_path),
        str(dem_path),
        "slope",
        options=gdal.DEMProcessingOptions(
            format="GTiff",
            creationOptions=["COMPRESS=DEFLATE"],
            computeEdges=True,
            alg="Horn",
            slopeFormat="degree",
        ),
    )
    if slope_dataset is None:
        raise RuntimeError("GDAL failed to calculate slope")
    slope_dataset = None
    aspect_dataset = gdal.DEMProcessing(
        str(aspect_path),
        str(dem_path),
        "aspect",
        options=gdal.DEMProcessingOptions(
            format="GTiff",
            creationOptions=["COMPRESS=DEFLATE"],
            computeEdges=True,
            alg="Horn",
            trigonometric=False,
            zeroForFlat=False,
        ),
    )
    if aspect_dataset is None:
        raise RuntimeError("GDAL failed to calculate aspect")
    aspect_dataset = None
    return slope_path, aspect_path


def _local_aeqd(context: ContextGrid) -> CRS:
    transformer = Transformer.from_crs(context.crs_epsg, 4326, always_xy=True)
    longitude, latitude = transformer.transform(
        (context.bounds.xmin + context.bounds.xmax) / 2,
        (context.bounds.ymin + context.bounds.ymax) / 2,
    )
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={latitude:.12f} +lon_0={longitude:.12f} "
        "+datum=WGS84 +units=m +no_defs"
    )


def _expanded_wgs84_bounds(
    context: ContextGrid, halo_m: float
) -> tuple[float, float, float, float]:
    transformer = Transformer.from_crs(context.crs_epsg, 4326, always_xy=True)
    return transformer.transform_bounds(
        context.bounds.xmin - halo_m,
        context.bounds.ymin - halo_m,
        context.bounds.xmax + halo_m,
        context.bounds.ymax + halo_m,
        densify_pts=21,
    )


def derive_srtm_terrain(
    source: str | Path,
    target: str | Path,
    context: ContextGrid,
    *,
    working_root: str | Path | None = None,
    halo_m: float = SRTM_HALO_M,
) -> Path:
    """Derive and aggregate terrain features locally from an SRTM elevation tile."""

    import numpy

    _validate_context(context)
    gdal = _gdal_module()
    source_path, target_path = Path(source), Path(target)
    if target_path.exists():
        raise FileExistsError(f"immutable SRTM target already exists: {target_path}")
    source_dataset = gdal.Open(str(source_path), gdal.GA_ReadOnly)
    if source_dataset is None or source_dataset.RasterCount != 1:
        raise ValueError("SRTM source must be a readable single-band raster")
    if not source_dataset.GetProjection():
        raise ValueError("SRTM source raster has no CRS")
    source_nodata = source_dataset.GetRasterBand(1).GetNoDataValue()
    source_dataset = None

    target_path.parent.mkdir(parents=True, exist_ok=True)
    scratch_parent = Path(working_root) if working_root is not None else target_path.parent / ".tmp"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    local_crs = _local_aeqd(context)
    to_local = Transformer.from_crs(context.crs_epsg, local_crs, always_xy=True)
    local_bounds = to_local.transform_bounds(
        context.bounds.xmin - halo_m,
        context.bounds.ymin - halo_m,
        context.bounds.xmax + halo_m,
        context.bounds.ymax + halo_m,
        densify_pts=21,
    )
    temporary_target = target_path.with_suffix(target_path.suffix + ".part")
    try:
        with tempfile.TemporaryDirectory(prefix="srtm-", dir=scratch_parent) as directory:
            scratch = Path(directory)
            local_dem = scratch / "dem_30m_aeqd.tif"
            slope = scratch / "slope_30m_aeqd.tif"
            aspect = scratch / "aspect_30m_aeqd.tif"
            components = scratch / "terrain_components_30m_aeqd.tif"
            averaged = scratch / "terrain_components_50m_epsg6933.tif"
            canonical = scratch / "terrain_stack_50m_epsg6933.tif"

            warped = gdal.Warp(
                str(local_dem),
                str(source_path),
                options=gdal.WarpOptions(
                    format="GTiff",
                    outputBounds=local_bounds,
                    xRes=SRTM_WORKING_RESOLUTION_M,
                    yRes=SRTM_WORKING_RESOLUTION_M,
                    dstSRS=local_crs.to_wkt(),
                    outputType=gdal.GDT_Float32,
                    srcNodata=source_nodata,
                    dstNodata=SRTM_OUTPUT_NODATA,
                    resampleAlg="bilinear",
                    creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
                ),
            )
            if warped is None:
                raise RuntimeError("GDAL failed to reproject the SRTM DEM")
            warped = None
            compute_slope_aspect_gdal(local_dem, slope, aspect)

            dem_dataset = gdal.Open(str(local_dem), gdal.GA_ReadOnly)
            slope_dataset = gdal.Open(str(slope), gdal.GA_ReadOnly)
            aspect_dataset = gdal.Open(str(aspect), gdal.GA_ReadOnly)
            elevation_values = dem_dataset.GetRasterBand(1).ReadAsArray().astype("float32")
            slope_values = slope_dataset.GetRasterBand(1).ReadAsArray().astype("float32")
            aspect_values = aspect_dataset.GetRasterBand(1).ReadAsArray().astype("float32")
            valid_elevation = numpy.isfinite(elevation_values) & (
                elevation_values != SRTM_OUTPUT_NODATA
            )
            valid_slope = numpy.isfinite(slope_values) & (slope_values != -9999.0)
            valid_aspect = numpy.isfinite(aspect_values) & (aspect_values != -9999.0)
            radians = numpy.deg2rad(aspect_values)
            eastness = numpy.sin(radians).astype("float32")
            northness = numpy.cos(radians).astype("float32")
            elevation_values[~valid_elevation] = SRTM_OUTPUT_NODATA
            slope_values[~valid_slope] = SRTM_OUTPUT_NODATA
            eastness[~valid_aspect] = SRTM_OUTPUT_NODATA
            northness[~valid_aspect] = SRTM_OUTPUT_NODATA

            driver = gdal.GetDriverByName("GTiff")
            component_dataset = driver.Create(
                str(components),
                dem_dataset.RasterXSize,
                dem_dataset.RasterYSize,
                4,
                gdal.GDT_Float32,
                options=["COMPRESS=DEFLATE", "TILED=YES"],
            )
            component_dataset.SetGeoTransform(dem_dataset.GetGeoTransform())
            component_dataset.SetProjection(dem_dataset.GetProjection())
            for index, (name, values) in enumerate(
                zip(
                    ("elevation_m", "slope_degrees", "eastness", "northness"),
                    (elevation_values, slope_values, eastness, northness),
                ),
                start=1,
            ):
                band = component_dataset.GetRasterBand(index)
                band.WriteArray(values)
                band.SetNoDataValue(SRTM_OUTPUT_NODATA)
                band.SetDescription(name)
            component_dataset = None
            dem_dataset = slope_dataset = aspect_dataset = None

            aggregated = gdal.Warp(
                str(averaged),
                str(components),
                options=gdal.WarpOptions(
                    format="GTiff",
                    outputBounds=(
                        context.bounds.xmin,
                        context.bounds.ymin,
                        context.bounds.xmax,
                        context.bounds.ymax,
                    ),
                    width=context.columns,
                    height=context.rows,
                    dstSRS=f"EPSG:{context.crs_epsg}",
                    outputType=gdal.GDT_Float32,
                    srcNodata=SRTM_OUTPUT_NODATA,
                    dstNodata=SRTM_OUTPUT_NODATA,
                    resampleAlg="average",
                    warpOptions=["UNIFIED_SRC_NODATA=NO"],
                    creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
                ),
            )
            if aggregated is None:
                raise RuntimeError("GDAL failed to aggregate SRTM terrain features")
            aggregated = None

            average_dataset = gdal.Open(str(averaged), gdal.GA_ReadOnly)
            elevation_50m, slope_50m, eastness_50m, northness_50m = (
                average_dataset.GetRasterBand(index).ReadAsArray().astype("float32")
                for index in range(1, 5)
            )
            valid_direction = (
                numpy.isfinite(eastness_50m)
                & numpy.isfinite(northness_50m)
                & (eastness_50m != SRTM_OUTPUT_NODATA)
                & (northness_50m != SRTM_OUTPUT_NODATA)
            )
            if (
                numpy.any(numpy.abs(eastness_50m[valid_direction]) > 1.0001)
                or numpy.any(numpy.abs(northness_50m[valid_direction]) > 1.0001)
            ):
                raise RuntimeError("invalid aspect components after GDAL aggregation")
            consistency = numpy.full(eastness_50m.shape, SRTM_OUTPUT_NODATA, dtype="float32")
            consistency[valid_direction] = numpy.hypot(
                eastness_50m[valid_direction], northness_50m[valid_direction]
            )
            aspect_50m = numpy.full(eastness_50m.shape, SRTM_OUTPUT_NODATA, dtype="float32")
            directional = valid_direction & (consistency > 1e-6)
            aspect_50m[directional] = (
                numpy.degrees(
                    numpy.arctan2(eastness_50m[directional], northness_50m[directional])
                )
                + 360.0
            ) % 360.0

            final_dataset = driver.Create(
                str(canonical),
                context.columns,
                context.rows,
                len(SRTM_OUTPUT_BANDS),
                gdal.GDT_Float32,
                options=["COMPRESS=DEFLATE", "TILED=YES"],
            )
            final_dataset.SetGeoTransform(average_dataset.GetGeoTransform())
            final_dataset.SetProjection(average_dataset.GetProjection())
            output_values = (
                elevation_50m,
                slope_50m,
                aspect_50m,
                eastness_50m,
                northness_50m,
                consistency,
            )
            for index, (name, values) in enumerate(
                zip(SRTM_OUTPUT_BANDS, output_values), start=1
            ):
                band = final_dataset.GetRasterBand(index)
                band.WriteArray(values)
                band.SetNoDataValue(SRTM_OUTPUT_NODATA)
                band.SetDescription(name)
            final_dataset.SetMetadata(
                {
                    "terrain_algorithm": "GDAL Horn",
                    "aspect_convention": "azimuth degrees clockwise from north",
                    "aspect_aggregation": "mean eastness/northness then atan2",
                    "working_crs": local_crs.to_string(),
                    "working_resolution_m": str(SRTM_WORKING_RESOLUTION_M),
                }
            )
            final_dataset = average_dataset = None
            translated = gdal.Translate(
                str(temporary_target),
                str(canonical),
                options=gdal.TranslateOptions(
                    format="COG",
                    creationOptions=[
                        "COMPRESS=DEFLATE",
                        "PREDICTOR=YES",
                        "BLOCKSIZE=256",
                        "OVERVIEWS=NONE",
                    ],
                ),
            )
            if translated is None:
                raise RuntimeError("GDAL failed to create the SRTM terrain COG")
            translated = None
        os.replace(temporary_target, target_path)
    finally:
        if temporary_target.exists():
            temporary_target.unlink()
    return target_path


