from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from sm_benchmark_agent.grid import (
    ContextResolution,
    anchor_cell_from_id,
    context_grid,
)
from sm_benchmark_agent.processing.srtm import _expanded_wgs84_bounds
from sm_benchmark_agent.processing.landcover import NATIVE_CRS as MODIS_SINUSOIDAL_CRS
from sm_benchmark_agent.processing.ndvi import (
    derive_mod13q1_ndvi_bytes,
)


def context_wgs84_bounds(context):
    return _expanded_wgs84_bounds(context, 0)


class MOD13Q1NDVITests(unittest.TestCase):
    def test_aqua_modis_crs_override_prevents_empty_reprojection(self) -> None:
        from pyproj import Transformer

        context = context_grid(
            anchor_cell_from_id("EASE2_M09km_R0203_C0632"),
            ContextResolution("250 m", 4),
        )
        transformer = Transformer.from_crs(
            6933, MODIS_SINUSOIDAL_CRS, always_xy=True
        )
        bounds = transformer.transform_bounds(
            context.bounds.xmin - 500,
            context.bounds.ymin - 500,
            context.bounds.xmax + 500,
            context.bounds.ymax + 500,
            densify_pts=41,
        )
        with MemoryFile() as memory:
            with memory.open(
                driver="GTiff",
                width=80,
                height=80,
                count=1,
                dtype="int16",
                # Reproduce the ellipsoidal WKT sometimes serialized by GEE
                # for pixels whose transform is actually MODIS sinusoidal.
                crs="+proj=sinu +datum=WGS84 +units=m +no_defs",
                transform=from_bounds(*bounds, 80, 80),
            ) as source:
                source.write(numpy.full((1, 80, 80), 5000, dtype="int16"))
            payload = memory.read()

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "aqua_override.tif"
            derive_mod13q1_ndvi_bytes(
                payload=payload,
                target=target,
                context=context,
                dates=[date(2022, 1, 9)],
                platform="Aqua",
                source_crs_override=MODIS_SINUSOIDAL_CRS,
                provenance={},
            )
            with rasterio.open(target) as output:
                values = output.read(1, masked=True)
                self.assertGreater(values.count(), 2500)
                self.assertAlmostEqual(float(values.mean()), 0.5, places=4)

    def test_aqua_metadata_and_scaling(self) -> None:
        import json
        from rasterio.transform import from_origin
        context = context_grid(anchor_cell_from_id("EASE2_M09km_R0108_C2017"), ContextResolution("250 m", 4))
        with MemoryFile() as memory:
            with memory.open(driver="GTiff", width=52, height=52, count=1,
                             dtype="int16", crs="EPSG:6933",
                             transform=from_origin(context.upper_left_x_m, context.upper_left_y_m,
                                                   context.exact_spacing_m, context.exact_spacing_m)) as src:
                src.write(numpy.full((1, 52, 52), 5000, dtype="int16"))
            payload = memory.read()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "aqua.tif"
            derive_mod13q1_ndvi_bytes(payload=payload, target=target, context=context,
                                     dates=[date(2002, 7, 4)], platform="Aqua", provenance={})
            with rasterio.open(target) as src:
                self.assertEqual(src.descriptions, ("2002-07-04_Aqua",))
                self.assertEqual(src.tags()["collection"], "MODIS/061/MYD13Q1")
                self.assertEqual(src.tags(1)["platform"], "Aqua")
                numpy.testing.assert_allclose(src.read(), .5)
            metadata = json.loads(target.with_suffix(".tif.manifest.json").read_text())
            self.assertEqual(metadata["platform"], "Aqua")
            self.assertEqual(metadata["collection"], "MODIS/061/MYD13Q1")

    def test_nas_stack_is_scaled_and_aligned_to_250m_context(self) -> None:
        context = context_grid(
            anchor_cell_from_id("EASE2_M09km_R0108_C2017"),
            ContextResolution("250 m", 4),
        )
        bounds = context_wgs84_bounds(context)
        values = numpy.empty((2, 90, 60), dtype="int16")
        values[0] = 5000
        values[1] = 7500
        values[:, :2, :] = -3000
        with MemoryFile() as memory:
            with memory.open(
                driver="GTiff",
                width=60,
                height=90,
                count=2,
                dtype="int16",
                crs="EPSG:4326",
                transform=from_bounds(*bounds, 60, 90),
            ) as source:
                source.write(values)
                source.set_band_description(1, "2017_01_01_2017_01_01")
                source.set_band_description(2, "2017_01_17_2017_01_17")
            payload = memory.read()

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "ndvi.tif"
            derive_mod13q1_ndvi_bytes(
                payload=payload,
                target=target,
                context=context,
                provenance={"provider": "test"},
            )
            with rasterio.open(target) as output:
                self.assertEqual(output.crs.to_epsg(), 6933)
                self.assertEqual((output.height, output.width), (52, 52))
                self.assertEqual(output.count, 2)
                self.assertEqual(
                    output.descriptions,
                    ("2017-01-01_Terra", "2017-01-17_Terra"),
                )
                first = output.read(1, masked=True)
                second = output.read(2, masked=True)
                self.assertAlmostEqual(float(first.mean()), 0.5, places=4)
                self.assertAlmostEqual(float(second.mean()), 0.75, places=4)
            self.assertTrue(target.with_suffix(".tif.manifest.json").exists())

    def test_anchor_id_constructor_is_exact(self) -> None:
        anchor = anchor_cell_from_id("EASE2_M09km_R0108_C2017")
        self.assertEqual(anchor.row, 108)
        self.assertEqual(anchor.column, 2017)
        self.assertEqual(anchor.anchor_id, "EASE2_M09km_R0108_C2017")


if __name__ == "__main__":
    unittest.main()
