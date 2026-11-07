"""V1 physical-overpass grouping and annual NetCDF assembly kernels.

Migrated from recorded production sources. Callers validate every input grid,
identity and band before assembly; corrupt rasters must not be silently dropped.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
import json
import re
import numpy as np
import pandas as pd
import rasterio
import xarray as xr

@dataclass(frozen=True, slots=True)
class Sentinel1Slice:
    scene_id: str
    time_start_ms: int
    orbit_pass: str
    relative_orbit: int
    absolute_orbit: int
    platform: str


@dataclass(frozen=True, slots=True)
class Sentinel1Acquisition:
    acquisition_id: str
    time_start_utc: str
    orbit_pass: str
    relative_orbit: int
    absolute_orbit: int
    platform: str
    scene_ids: tuple[str, ...]


def group_sentinel1_slices(
    slices: Iterable[Sentinel1Slice],
) -> list[Sentinel1Acquisition]:
    """Group adjacent ROI-intersecting slices from the same satellite orbit."""

    groups: dict[tuple[str, int, str], list[Sentinel1Slice]] = {}
    for item in slices:
        key = (item.platform, item.absolute_orbit, item.orbit_pass)
        groups.setdefault(key, []).append(item)
    acquisitions: list[Sentinel1Acquisition] = []
    for items in groups.values():
        ordered = sorted(items, key=lambda item: (item.time_start_ms, item.scene_id))
        first = ordered[0]
        stamp = datetime.fromtimestamp(
            first.time_start_ms / 1000, timezone.utc
        ).strftime("%Y%m%dT%H%M%SZ")
        acquisition_id = (
            f"S1{first.platform}_{stamp}_{first.orbit_pass}_"
            f"R{first.relative_orbit:03d}_O{first.absolute_orbit:06d}"
        )
        acquisitions.append(
            Sentinel1Acquisition(
                acquisition_id=acquisition_id,
                time_start_utc=datetime.fromtimestamp(
                    first.time_start_ms / 1000, timezone.utc
                ).isoformat(),
                orbit_pass=first.orbit_pass,
                relative_orbit=first.relative_orbit,
                absolute_orbit=first.absolute_orbit,
                platform=first.platform,
                scene_ids=tuple(item.scene_id for item in ordered),
            )
        )
    return sorted(acquisitions, key=lambda item: item.time_start_utc)


def stack_sentinel1(
    pairs: list[tuple[Path, Path]], target: Path
) -> dict[str, object]:
    records: list[tuple[dict[str, object], Path]] = []
    for raster, manifest in pairs:
        document = json.loads(manifest.read_text(encoding="utf-8"))
        properties = (document.get("scene_properties") or [{}])[0]
        time_ms = properties.get("system:time_start")
        if time_ms is None and document.get("time_start_utc"):
            time_ms = int(
                pd.Timestamp(document["time_start_utc"]).timestamp() * 1000
            )
        if time_ms is None:
            match = re.search(r"(\d{8}T\d{6})", raster.name)
            if not match:
                match = re.search(r"(\d{8}T\d{6})", raster.parent.parent.name)
            if not match:
                raise ValueError(f"Sentinel-1 acquisition time is unavailable: {manifest}")
            time_ms = int(
                datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
                .replace(tzinfo=timezone.utc)
                .timestamp()
                * 1000
            )
        records.append(({
            "time_ms": int(time_ms),
            "platform": str(properties.get("platform_number", document.get("platform", ""))),
            "orbit_pass": str(properties.get("orbitProperties_pass", document.get("orbit_pass", ""))),
            "absolute_orbit": int(properties.get("orbitNumber_start", document.get("absolute_orbit", -1))),
            "relative_orbit": int(properties.get("relativeOrbitNumber_start", document.get("relative_orbit", -1))),
            "source_scene_id": str((document.get("scene_ids") or [""])[0]),
            "acquisition_id": str(document.get("snapshot_id", document.get("acquisition_id", raster.parent.parent.name))),
            "bands": [str(value) for value in document.get("bands", [])],
        }, raster))
    records.sort(key=lambda item: int(item[0]["time_ms"]))
    if not records:
        raise ValueError("Sentinel-1 state is available but no acquisitions were indexed")
    arrays = [[], [], []]
    metadata: list[dict[str, object]] = []
    spatial = None
    excluded: list[str] = []
    for item, raster in records:
        try:
            with rasterio.open(raster) as dataset:
                descriptions = [
                    (description or "").strip().lower()
                    for description in dataset.descriptions
                ]
                declared = [value.strip().lower() for value in item["bands"]]
                names = descriptions if any(descriptions) else declared
                if len(names) != dataset.count:
                    names = ["vv", "vh", "angle"][: dataset.count]
                by_name = {name: index for index, name in enumerate(names, 1)}
                shape = (dataset.height, dataset.width)
                current_values: list[np.ndarray] = []
                for output_index, name in enumerate(("vv", "vh", "angle")):
                    source_index = by_name.get(name)
                    if source_index is None and name == "angle":
                        source_index = by_name.get("incidence_angle")
                    if source_index is None:
                        value = np.full(shape, np.nan, dtype="float32")
                    else:
                        value = (
                            dataset.read(source_index, masked=True)
                            .filled(np.nan)
                            .astype("float32")
                        )
                    current_values.append(value)
                if spatial is None:
                    spatial = (dataset.height, dataset.width, dataset.transform, dataset.crs.to_wkt())
            for output_index, value in enumerate(current_values):
                arrays[output_index].append(value)
            metadata.append(item)
        except rasterio.errors.RasterioError:
            excluded.append(item["acquisition_id"])
    assert spatial is not None
    height, width, transform, crs_wkt = spatial
    x = transform.c + (np.arange(width) + 0.5) * transform.a
    y = transform.f + (np.arange(height) + 0.5) * transform.e
    if not metadata:
        raise ValueError("all indexed Sentinel-1 acquisitions failed raster validation")
    times = np.array([np.datetime64(int(item["time_ms"]), "ms") for item in metadata])
    dataset = xr.Dataset(
        data_vars={
            "vv": (("time", "y", "x"), np.stack(arrays[0]), {"units": "dB", "long_name": "VV backscatter"}),
            "vh": (("time", "y", "x"), np.stack(arrays[1]), {"units": "dB", "long_name": "VH backscatter"}),
            "incidence_angle": (("time", "y", "x"), np.stack(arrays[2]), {"units": "degree", "long_name": "incidence angle"}),
            "platform": (("time",), np.asarray([item["platform"] for item in metadata], dtype="U1")),
            "orbit_pass": (("time",), np.asarray([item["orbit_pass"] for item in metadata], dtype="U10")),
            "absolute_orbit": (("time",), np.asarray([item["absolute_orbit"] for item in metadata], dtype="int32")),
            "relative_orbit": (("time",), np.asarray([item["relative_orbit"] for item in metadata], dtype="int16")),
            "acquisition_id": (("time",), np.asarray([item["acquisition_id"] for item in metadata], dtype="U80")),
            "source_scene_id": (("time",), np.asarray([item["source_scene_id"] for item in metadata], dtype="U160")),
            "crs": ((), np.int16(0), {"spatial_ref": crs_wkt, "grid_mapping_name": "lambert_cylindrical_equal_area", "epsg_code": "EPSG:6933"}),
        },
        coords={"time": times, "x": x, "y": y},
        attrs={
            "title": "Annual Sentinel-1 acquisition stack for one benchmark anchor",
            "source_product": "COPERNICUS/S1_GRD",
            "spatial_representation": "nominal 50 m context grid in EPSG:6933",
            "backscatter_aggregation": "linear-power mean followed by conversion to decibels",
            "incidence_angle_aggregation": "arithmetic mean in degrees",
            "temporal_representation": "individual acquisitions retained without temporal compositing",
        },
    )
    for variable in ("vv", "vh", "incidence_angle"):
        dataset[variable].attrs["grid_mapping"] = "crs"
    encoding = {
        variable: {
            "compression": "gzip",
            "compression_opts": 4,
            "shuffle": True,
            "chunksizes": (1, height, width),
            "_FillValue": np.float32(np.nan),
        }
        for variable in ("vv", "vh", "incidence_angle")
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_netcdf(target, engine="h5netcdf", encoding=encoding)
    dataset.close()
    return {
        "acquisition_count": len(metadata),
        "excluded_acquisition_count": len(excluded),
        "excluded_acquisition_ids": excluded,
        "first_acquisition_utc": str(times.min()),
        "last_acquisition_utc": str(times.max()),
        "variables": ["vv", "vh", "incidence_angle"],
    }


