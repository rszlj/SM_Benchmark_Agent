from __future__ import annotations

import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from sm_benchmark_agent.grid import ContextResolution, anchor_cell, context_grid
from sm_benchmark_agent.processing.hwsd2 import (
    HWSD2NoSoilDataError,
    HWSD2_LAYERS,
    HWSD2_NUMERIC_PROPERTIES,
    extract_hwsd2_tile,
    stream_hwsd2_raster_zip,
)


class HWSD2Tests(unittest.TestCase):
    def test_streams_bil_from_zip_without_extracting_it(self) -> None:
        import numpy
        import rasterio

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "raster.zip"
            target = root / "global.tif"
            values = numpy.arange(12, dtype="<u2").reshape(3, 4)
            header = """BYTEORDER I
LAYOUT BIL
NROWS 3
NCOLS 4
NBANDS 1
NBITS 16
PIXELTYPE UNSIGNEDINT
ULXMAP -179.5
ULYMAP 89.5
XDIM 1
YDIM 1
NODATA 65535
"""
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("HWSD2.hdr", header)
                package.writestr("HWSD2.bil", values.tobytes())
            stream_hwsd2_raster_zip(archive, target, chunk_rows=2)
            with rasterio.open(target) as dataset:
                self.assertEqual((dataset.height, dataset.width), (3, 4))
                self.assertEqual(dataset.crs.to_epsg(), 4326)
                numpy.testing.assert_array_equal(dataset.read(1), values)

    def test_tile_preserves_components_and_builds_weighted_layers(self) -> None:
        import numpy
        import rasterio
        from rasterio.transform import from_bounds

        context = context_grid(
            anchor_cell(-86.9023, 32.3182), ContextResolution("1 km", 1)
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "global.tif"
            database = root / "HWSD2.sqlite"
            values = numpy.full((26, 26), 100, dtype="uint16")
            values[:, 13:] = 200
            with rasterio.open(
                source,
                "w",
                driver="GTiff",
                width=26,
                height=26,
                count=1,
                dtype="uint16",
                crs="EPSG:6933",
                transform=from_bounds(
                    context.bounds.xmin,
                    context.bounds.ymin,
                    context.bounds.xmax,
                    context.bounds.ymax,
                    26,
                    26,
                ),
                nodata=65535,
            ) as dataset:
                dataset.write(values, 1)
            connection = sqlite3.connect(database)
            property_definitions = ",".join(
                f'"{name}" REAL' for name in HWSD2_NUMERIC_PROPERTIES
            )
            connection.execute(
                "CREATE TABLE HWSD2_LAYERS (HWSD2_SMU_ID INTEGER, "
                "LAYER TEXT, SEQUENCE INTEGER, SHARE REAL, TOPDEP INTEGER, "
                f"BOTDEP INTEGER, {property_definitions})"
            )
            connection.execute(
                "CREATE TABLE HWSD2_LAYERS_METADATA "
                "(FIELD TEXT, UNIT TEXT, DESCRIPTION TEXT)"
            )
            connection.executemany(
                "INSERT INTO HWSD2_LAYERS_METADATA VALUES (?, ?, ?)",
                [(name, "test-unit", name) for name in HWSD2_NUMERIC_PROPERTIES],
            )
            columns = ",".join(HWSD2_NUMERIC_PROPERTIES)
            placeholders = ",".join("?" for _ in HWSD2_NUMERIC_PROPERTIES)
            for smu_id in (100, 200):
                for layer, top, bottom in HWSD2_LAYERS:
                    for sequence, share, value in ((1, 25, 1.0), (2, 75, 3.0)):
                        property_values = [value] * len(HWSD2_NUMERIC_PROPERTIES)
                        if sequence == 1:
                            property_values[0] = -9.0
                        connection.execute(
                            "INSERT INTO HWSD2_LAYERS "
                            "(HWSD2_SMU_ID,LAYER,SEQUENCE,SHARE,TOPDEP,BOTDEP,"
                            f"{columns}) VALUES (?,?,?,?,?,?,{placeholders})",
                            (
                                smu_id,
                                layer,
                                sequence,
                                share,
                                top,
                                bottom,
                                *property_values,
                            ),
                        )
            connection.commit()
            connection.close()

            outputs = extract_hwsd2_tile(
                global_raster=source,
                sqlite_database=database,
                context=context,
                output_root=root / "output",
            )
            with rasterio.open(outputs["properties_raster"]) as dataset:
                self.assertEqual(dataset.count, 140)
                self.assertEqual((dataset.height, dataset.width), (13, 13))
                # The first property excludes the -9 HWSD2 source code and
                # renormalizes the remaining component to 100%.
                self.assertAlmostEqual(float(dataset.read(1).mean()), 3.0, places=5)
                self.assertAlmostEqual(float(dataset.read(2).mean()), 2.5, places=5)
                self.assertEqual(dataset.tags(1)["unit"], "test-unit")
            lines = outputs["components_csv"].read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1 + 2 * 7 * 2)

    def test_no_soil_tile_leaves_no_partial_output(self) -> None:
        import numpy
        import rasterio
        from rasterio.transform import from_bounds

        context = context_grid(
            anchor_cell(-86.9023, 32.3182), ContextResolution("1 km", 1)
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "global.tif"
            database = root / "HWSD2.sqlite"
            with rasterio.open(
                source, "w", driver="GTiff", width=13, height=13, count=1,
                dtype="uint16", crs="EPSG:6933",
                transform=from_bounds(
                    context.bounds.xmin, context.bounds.ymin,
                    context.bounds.xmax, context.bounds.ymax, 13, 13,
                ),
                nodata=65535,
            ) as dataset:
                dataset.write(numpy.full((13, 13), 65535, dtype="uint16"), 1)
            sqlite3.connect(database).close()
            output = root / "output"
            with self.assertRaises(HWSD2NoSoilDataError):
                extract_hwsd2_tile(
                    global_raster=source, sqlite_database=database,
                    context=context, output_root=output,
                )
            self.assertEqual(
                [path.name for path in output.rglob("*") if path.is_file()], []
            )


if __name__ == "__main__":
    unittest.main()
