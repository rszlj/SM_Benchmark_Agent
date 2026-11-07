"""Official HWSD 2.0 preparation and local tile extraction."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen

from ..grid import ContextGrid
from .srtm import _gdal_module


HWSD2_SNAPSHOT_ID = "HWSD2.0-20230923"
HWSD2_RASTER_URL = (
    "https://s3.eu-west-1.amazonaws.com/data.gaezdev.aws.fao.org/"
    "HWSD/HWSD2_RASTER.zip"
)
HWSD2_DATABASE_URL = (
    "https://s3.eu-west-1.amazonaws.com/data.gaezdev.aws.fao.org/"
    "HWSD/HWSD2_DB.zip"
)
HWSD2_RASTER_SHA256 = "55612130174f228f48d0691a2e01ab92150617dfd0d6605e65e3619eb5c123d8"
HWSD2_DATABASE_SHA256 = "6c69e09137a8150f53c8a893fe3e4426d6b5cceb635c00378b54b7d64a9736c0"
HWSD2_SMU_NODATA = 65535
HWSD2_FLOAT_NODATA = -9999.0


class HWSD2NoSoilDataError(RuntimeError):
    """Raised when an anchor context contains no HWSD2 soil mapping unit."""
HWSD2_LAYERS = (
    ("D1", 0, 20),
    ("D2", 20, 40),
    ("D3", 40, 60),
    ("D4", 60, 80),
    ("D5", 80, 100),
    ("D6", 100, 150),
    ("D7", 150, 200),
)
HWSD2_NUMERIC_PROPERTIES = (
    "COARSE",
    "SAND",
    "SILT",
    "CLAY",
    "BULK",
    "REF_BULK",
    "ORG_CARBON",
    "PH_WATER",
    "TOTAL_N",
    "CN_RATIO",
    "CEC_SOIL",
    "CEC_CLAY",
    "CEC_EFF",
    "TEB",
    "BSAT",
    "ALUM_SAT",
    "ESP",
    "TCARBON_EQ",
    "GYPSUM",
    "ELEC_COND",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_verified(url: str, target: Path, expected_sha256: str) -> Path:
    if target.exists():
        actual = _sha256(target)
        if actual != expected_sha256:
            raise ValueError(f"checksum mismatch for existing archive: {target}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with urlopen(url, timeout=300) as response, temporary.open("wb") as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
        actual = _sha256(temporary)
        if actual != expected_sha256:
            raise RuntimeError(
                f"downloaded archive checksum mismatch: expected {expected_sha256}, got {actual}"
            )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def _parse_hdr(text: str) -> dict[str, str]:
    fields = {}
    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            fields[parts[0].upper()] = parts[1].strip()
    return fields


def stream_hwsd2_raster_zip(
    archive: str | Path,
    target: str | Path,
    *,
    chunk_rows: int = 256,
) -> Path:
    """Stream the compressed global BIL into a tiled compressed GeoTIFF."""

    import numpy
    import rasterio
    from rasterio.transform import from_origin

    archive_path, target_path = Path(archive), Path(target)
    if target_path.exists():
        raise FileExistsError(f"immutable HWSD2 global raster already exists: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_suffix(target_path.suffix + ".part")
    try:
        with zipfile.ZipFile(archive_path) as package:
            names = package.namelist()
            bil_name = next(name for name in names if name.lower().endswith(".bil"))
            hdr_name = next(name for name in names if name.lower().endswith(".hdr"))
            header = _parse_hdr(package.read(hdr_name).decode("ascii"))
            rows = int(header["NROWS"])
            columns = int(header["NCOLS"])
            if (
                header.get("LAYOUT", "").upper() != "BIL"
                or int(header["NBANDS"]) != 1
                or int(header["NBITS"]) != 16
                or header.get("PIXELTYPE", "").upper() != "UNSIGNEDINT"
            ):
                raise ValueError("unsupported HWSD2 raster layout")
            x_size = float(header["XDIM"])
            y_size = float(header["YDIM"])
            x_origin = float(header["ULXMAP"]) - x_size / 2
            y_origin = float(header["ULYMAP"]) + y_size / 2
            nodata = int(header["NODATA"])
            byte_order = "<" if header.get("BYTEORDER", "I").upper() == "I" else ">"
            profile = {
                "driver": "GTiff",
                "width": columns,
                "height": rows,
                "count": 1,
                "dtype": "uint16",
                "crs": "EPSG:4326",
                "transform": from_origin(x_origin, y_origin, x_size, y_size),
                "nodata": nodata,
                "compress": "deflate",
                "predictor": 2,
                "zlevel": 6,
                "tiled": True,
                "blockxsize": 512,
                "blockysize": 512,
                "BIGTIFF": "IF_SAFER",
            }
            expected_bytes = rows * columns * 2
            consumed = 0
            with package.open(bil_name) as source, rasterio.open(
                temporary, "w", **profile
            ) as destination:
                for row_start in range(0, rows, chunk_rows):
                    row_count = min(chunk_rows, rows - row_start)
                    byte_count = row_count * columns * 2
                    payload = source.read(byte_count)
                    if len(payload) != byte_count:
                        raise RuntimeError("truncated HWSD2 BIL stream")
                    consumed += len(payload)
                    values = numpy.frombuffer(
                        payload, dtype=f"{byte_order}u2"
                    ).reshape(row_count, columns)
                    destination.write(
                        values,
                        1,
                        window=((row_start, row_start + row_count), (0, columns)),
                    )
                if consumed != expected_bytes or source.read(1):
                    raise RuntimeError("unexpected HWSD2 BIL byte count")
                destination.set_band_description(1, "HWSD2_SMU_ID")
                destination.update_tags(
                    source_archive=archive_path.name,
                    source_format="ESRI BIL streamed from ZIP",
                )
        os.replace(temporary, target_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target_path


def _sqlite_type(values) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool | int):
            return "INTEGER"
        if isinstance(value, float):
            return "REAL"
        if isinstance(value, bytes):
            return "BLOB"
        return "TEXT"
    return "TEXT"


def _sqlite_value(value):
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    return value


def convert_hwsd2_mdb_to_sqlite(
    mdb_file: str | Path,
    target: str | Path,
) -> Path:
    """Convert official HWSD tables to portable SQLite using pure Python."""

    try:
        from access_parser import AccessParser
    except ImportError as exc:
        raise RuntimeError(
            "HWSD2 database conversion requires the optional 'hwsd' dependencies"
        ) from exc
    target_path = Path(target)
    if target_path.exists():
        raise FileExistsError(f"immutable HWSD2 SQLite database already exists: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_suffix(target_path.suffix + ".part")
    parser = AccessParser(str(mdb_file))
    table_names = [
        name
        for name in parser.catalog
        if name.startswith("D_")
        or name
        in {
            "HWSD2_SMU",
            "HWSD2_LAYERS",
            "HWSD2_SMU_METADATA",
            "HWSD2_LAYERS_METADATA",
        }
    ]
    connection = sqlite3.connect(temporary)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        for table_name in table_names:
            data = parser.get_table(table_name).parse()
            columns = list(data)
            definitions = ", ".join(
                f'"{column}" {_sqlite_type(data[column])}' for column in columns
            )
            connection.execute(f'CREATE TABLE "{table_name}" ({definitions})')
            placeholders = ", ".join("?" for _ in columns)
            quoted_columns = ", ".join(f'"{column}"' for column in columns)
            statement = (
                f'INSERT INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})'
            )
            row_count = len(data[columns[0]])
            for start in range(0, row_count, 5000):
                end = min(start + 5000, row_count)
                rows = (
                    tuple(_sqlite_value(data[column][index]) for column in columns)
                    for index in range(start, end)
                )
                connection.executemany(statement, rows)
            connection.commit()
        connection.execute(
            "CREATE UNIQUE INDEX hwsd2_smu_id_idx ON HWSD2_SMU(HWSD2_SMU_ID)"
        )
        connection.execute(
            "CREATE INDEX hwsd2_layers_lookup_idx "
            "ON HWSD2_LAYERS(HWSD2_SMU_ID, LAYER, SEQUENCE)"
        )
        connection.execute("ANALYZE")
        connection.commit()
        connection.close()
        os.replace(temporary, target_path)
    except Exception:
        connection.close()
        raise
    finally:
        if temporary.exists():
            temporary.unlink()
    return target_path


def _extract_mdb(archive: Path, target: Path) -> Path:
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with zipfile.ZipFile(archive) as package:
            member = next(name for name in package.namelist() if name.lower().endswith(".mdb"))
            with package.open(member) as source, temporary.open("wb") as output:
                while block := source.read(1024 * 1024):
                    output.write(block)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def prepare_hwsd2_global(cache_root: str | Path) -> dict[str, Path]:
    """Download and prepare the global HWSD2 raster and portable database once."""

    root = Path(cache_root) / HWSD2_SNAPSHOT_ID
    archives = root / "archives"
    raster_archive = _download_verified(
        HWSD2_RASTER_URL, archives / "HWSD2_RASTER.zip", HWSD2_RASTER_SHA256
    )
    database_archive = _download_verified(
        HWSD2_DATABASE_URL, archives / "HWSD2_DB.zip", HWSD2_DATABASE_SHA256
    )
    global_raster = root / "prepared" / "HWSD2_SMU_global_compressed.tif"
    sqlite_database = root / "prepared" / "HWSD2.sqlite"
    if not global_raster.exists():
        stream_hwsd2_raster_zip(raster_archive, global_raster)
    if not sqlite_database.exists():
        with tempfile.TemporaryDirectory(prefix="hwsd2-mdb-", dir=root) as directory:
            mdb = _extract_mdb(database_archive, Path(directory) / "HWSD2.mdb")
            convert_hwsd2_mdb_to_sqlite(mdb, sqlite_database)
    manifest = root / "prepared" / "prepared.manifest.json"
    metadata = {
        "snapshot_id": HWSD2_SNAPSHOT_ID,
        "provider": "FAO and IIASA",
        "archives": {
            "raster": {
                "url": HWSD2_RASTER_URL,
                "file": str(raster_archive),
                "sha256": HWSD2_RASTER_SHA256,
            },
            "database": {
                "url": HWSD2_DATABASE_URL,
                "file": str(database_archive),
                "sha256": HWSD2_DATABASE_SHA256,
            },
        },
        "prepared": {
            "global_raster": {
                "file": str(global_raster),
                "sha256": _sha256(global_raster),
            },
            "sqlite_database": {
                "file": str(sqlite_database),
                "sha256": _sha256(sqlite_database),
            },
        },
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary_manifest = manifest.with_suffix(manifest.suffix + ".part")
    temporary_manifest.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest)
    return {
        "raster_archive": raster_archive,
        "database_archive": database_archive,
        "global_raster": global_raster,
        "sqlite_database": sqlite_database,
        "manifest": manifest,
    }


def _validate_context(context: ContextGrid) -> None:
    if (
        context.nominal_resolution != "1 km"
        or context.rows != 13
        or context.columns != 13
    ):
        raise ValueError("HWSD2 canonical output requires ContextResolution('1 km', 1)")


def _write_component_csv(
    connection: sqlite3.Connection,
    smu_ids: list[int],
    target: Path,
) -> None:
    placeholders = ",".join("?" for _ in smu_ids)
    cursor = connection.execute(
        f"SELECT * FROM HWSD2_LAYERS WHERE HWSD2_SMU_ID IN ({placeholders}) "
        "ORDER BY HWSD2_SMU_ID, SEQUENCE, TOPDEP",
        smu_ids,
    )
    temporary = target.with_suffix(target.suffix + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(column[0] for column in cursor.description)
        writer.writerows(cursor)
    os.replace(temporary, target)


def extract_hwsd2_tile(
    *,
    global_raster: str | Path,
    sqlite_database: str | Path,
    context: ContextGrid,
    output_root: str | Path,
    snapshot_id: str = HWSD2_SNAPSHOT_ID,
    tile_directory: str | Path | None = None,
) -> dict[str, Path]:
    """Extract mapping units and share-weighted seven-layer soil properties."""

    import numpy

    _validate_context(context)
    gdal = _gdal_module()
    directory = Path(tile_directory) if tile_directory is not None else (
        Path(output_root)
        / "derived"
        / "hwsd2"
        / snapshot_id
        / context.anchor_id
    )
    smu_raster = directory / "hwsd2_smu_1km_EPSG6933.tif"
    properties_raster = directory / "hwsd2_properties_7layers_1km_EPSG6933.tif"
    components_csv = directory / "hwsd2_components_7layers.csv"
    manifest = directory / "hwsd2.manifest.json"
    outputs = (smu_raster, properties_raster, components_csv, manifest)
    if all(path.exists() for path in outputs):
        return {
            "smu_raster": smu_raster,
            "properties_raster": properties_raster,
            "components_csv": components_csv,
            "manifest": manifest,
        }
    if any(path.exists() for path in outputs):
        raise FileExistsError("partial immutable HWSD2 tile already exists")
    directory.mkdir(parents=True, exist_ok=True)

    temporary_smu = smu_raster.with_suffix(smu_raster.suffix + ".part")
    warped = gdal.Warp(
        str(temporary_smu),
        str(global_raster),
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
            outputType=gdal.GDT_UInt16,
            srcNodata=HWSD2_SMU_NODATA,
            dstNodata=HWSD2_SMU_NODATA,
            resampleAlg="mode",
            creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
        ),
    )
    if warped is None:
        raise RuntimeError("GDAL failed to extract HWSD2 mapping units")
    warped.GetRasterBand(1).SetDescription("HWSD2_SMU_ID")
    warped.SetMetadataItem("resampling", "mode")
    warped = None
    smu_dataset = gdal.Open(str(temporary_smu), gdal.GA_ReadOnly)
    smu_values = smu_dataset.GetRasterBand(1).ReadAsArray()
    smu_ids = sorted(
        int(value)
        for value in numpy.unique(smu_values)
        if int(value) != HWSD2_SMU_NODATA
    )
    if not smu_ids:
        smu_dataset = None
        temporary_smu.unlink(missing_ok=True)
        Path(str(temporary_smu) + ".aux.xml").unlink(missing_ok=True)
        raise HWSD2NoSoilDataError("HWSD2 tile contains no soil mapping units")
    smu_dataset = None
    os.replace(temporary_smu, smu_raster)
    smu_dataset = gdal.Open(str(smu_raster), gdal.GA_ReadOnly)
    smu_transform = smu_dataset.GetGeoTransform()
    smu_projection = smu_dataset.GetProjection()
    smu_dataset = None
    connection = sqlite3.connect(sqlite_database)
    connection.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in smu_ids)
    selected = ", ".join(HWSD2_NUMERIC_PROPERTIES)
    try:
        rows = connection.execute(
            f"SELECT HWSD2_SMU_ID, LAYER, SHARE, {selected} FROM HWSD2_LAYERS "
            f"WHERE HWSD2_SMU_ID IN ({placeholders})",
            smu_ids,
        ).fetchall()
        metadata_rows = connection.execute(
            "SELECT FIELD, UNIT, DESCRIPTION FROM HWSD2_LAYERS_METADATA"
        ).fetchall()
        field_metadata = {row["FIELD"]: dict(row) for row in metadata_rows}
        _write_component_csv(connection, smu_ids, components_csv)
    finally:
        connection.close()

    grouped = defaultdict(list)
    for row in rows:
        grouped[(int(row["HWSD2_SMU_ID"]), row["LAYER"])].append(row)
    lookup = {}
    for key, component_rows in grouped.items():
        property_values = {}
        for prop in HWSD2_NUMERIC_PROPERTIES:
            weighted_sum = 0.0
            weight_sum = 0.0
            for row in component_rows:
                value, share = row[prop], row["SHARE"]
                # HWSD2 encodes unavailable numeric properties with negative
                # integers (-1 through -9). They are source missing-value
                # codes, not physical measurements, and must be excluded
                # before component shares are renormalized.
                if (
                    value is not None
                    and share is not None
                    and numpy.isfinite(float(value))
                    and float(value) >= 0
                    and float(share) > 0
                ):
                    weighted_sum += float(value) * float(share)
                    weight_sum += float(share)
            property_values[prop] = (
                weighted_sum / weight_sum if weight_sum else None
            )
        lookup[key] = property_values

    temporary_properties = properties_raster.with_suffix(properties_raster.suffix + ".part")
    driver = gdal.GetDriverByName("GTiff")
    property_dataset = driver.Create(
        str(temporary_properties),
        context.columns,
        context.rows,
        len(HWSD2_LAYERS) * len(HWSD2_NUMERIC_PROPERTIES),
        gdal.GDT_Float32,
        options=["COMPRESS=DEFLATE", "TILED=YES"],
    )
    property_dataset.SetGeoTransform(smu_transform)
    property_dataset.SetProjection(smu_projection)
    band_index = 1
    band_manifest = []
    for layer, top_cm, bottom_cm in HWSD2_LAYERS:
        for prop in HWSD2_NUMERIC_PROPERTIES:
            values = numpy.full(
                (context.rows, context.columns),
                HWSD2_FLOAT_NODATA,
                dtype="float32",
            )
            for smu_id in smu_ids:
                value = lookup.get((smu_id, layer), {}).get(prop)
                if value is not None:
                    values[smu_values == smu_id] = value
            band = property_dataset.GetRasterBand(band_index)
            band.WriteArray(values)
            band.SetNoDataValue(HWSD2_FLOAT_NODATA)
            band.SetDescription(f"{layer}_{top_cm}-{bottom_cm}cm_{prop}")
            info = field_metadata.get(prop, {})
            band.SetMetadata(
                {
                    "layer": layer,
                    "top_depth_cm": str(top_cm),
                    "bottom_depth_cm": str(bottom_cm),
                    "property": prop,
                    "unit": str(info.get("UNIT") or ""),
                    "description": str(info.get("DESCRIPTION") or ""),
                    "component_aggregation": "share-weighted mean after excluding negative HWSD2 missing-value codes and renormalizing valid component shares",
                }
            )
            band_manifest.append(
                {
                    "band": band_index,
                    "layer": layer,
                    "top_depth_cm": top_cm,
                    "bottom_depth_cm": bottom_cm,
                    "property": prop,
                    "unit": info.get("UNIT"),
                    "description": info.get("DESCRIPTION"),
                }
            )
            band_index += 1
    property_dataset.SetMetadataItem(
        "component_aggregation", "share-weighted mean after excluding negative HWSD2 missing-value codes and renormalizing valid component shares"
    )
    property_dataset = smu_dataset = None
    os.replace(temporary_properties, properties_raster)

    metadata = {
        "snapshot_id": snapshot_id,
        "provider": "FAO and IIASA",
        "mapping_unit_resampling": "mode",
        "component_aggregation": "share-weighted mean after excluding negative HWSD2 missing-value codes and renormalizing valid component shares",
        "smu_ids": smu_ids,
        "bands": band_manifest,
        "outputs": {
            "smu_raster": {"file": str(smu_raster), "sha256": _sha256(smu_raster)},
            "properties_raster": {
                "file": str(properties_raster),
                "sha256": _sha256(properties_raster),
            },
            "components_csv": {
                "file": str(components_csv),
                "sha256": _sha256(components_csv),
            },
        },
    }
    temporary_manifest = manifest.with_suffix(manifest.suffix + ".part")
    temporary_manifest.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest)
    return {
        "smu_raster": smu_raster,
        "properties_raster": properties_raster,
        "components_csv": components_csv,
        "manifest": manifest,
    }
