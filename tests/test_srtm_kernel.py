from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from sm_benchmark_agent.grid import ContextResolution, anchor_cell, context_grid
from sm_benchmark_agent.processing.srtm import SRTM_OUTPUT_BANDS, compute_slope_aspect_gdal, derive_srtm_terrain


class GEESRTMTests(unittest.TestCase):
    def test_gdal_horn_slope_and_aspect_on_east_rising_plane(self) -> None:
        import numpy
        from osgeo import gdal, osr

        gdal.UseExceptions()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dem = root / "dem.tif"
            slope = root / "slope.tif"
            aspect = root / "aspect.tif"
            driver = gdal.GetDriverByName("GTiff")
            dataset = driver.Create(str(dem), 9, 9, 1, gdal.GDT_Float32)
            dataset.SetGeoTransform((0.0, 30.0, 0.0, 270.0, 0.0, -30.0))
            spatial_ref = osr.SpatialReference()
            spatial_ref.ImportFromEPSG(6933)
            dataset.SetProjection(spatial_ref.ExportToWkt())
            values = numpy.tile(numpy.arange(9, dtype="float32") * 3.0, (9, 1))
            dataset.GetRasterBand(1).WriteArray(values)
            dataset = None

            compute_slope_aspect_gdal(dem, slope, aspect)
            slope_dataset = gdal.Open(str(slope))
            aspect_dataset = gdal.Open(str(aspect))
            self.assertAlmostEqual(
                float(slope_dataset.GetRasterBand(1).ReadAsArray()[4, 4]),
                math.degrees(math.atan(0.1)),
                places=4,
            )
            self.assertAlmostEqual(
                float(aspect_dataset.GetRasterBand(1).ReadAsArray()[4, 4]),
                270.0,
                places=4,
            )
            slope_dataset = aspect_dataset = None

    def test_local_processing_creates_exact_50m_context(self) -> None:
        import numpy
        import rasterio
        from osgeo import gdal
        from rasterio.transform import from_bounds

        context = context_grid(
            anchor_cell(-86.9023, 32.3182), ContextResolution("50 m", 20)
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tif"
            target = root / "terrain.tif"
            expanded = 500.0
            bounds = (
                context.bounds.xmin - expanded,
                context.bounds.ymin - expanded,
                context.bounds.xmax + expanded,
                context.bounds.ymax + expanded,
            )
            with rasterio.open(
                source,
                "w",
                driver="GTiff",
                width=480,
                height=480,
                count=1,
                dtype="float32",
                crs="EPSG:6933",
                transform=from_bounds(*bounds, 480, 480),
                nodata=-32768.0,
            ) as dataset:
                rows, columns = numpy.indices((480, 480), dtype="float32")
                values = 100.0 + columns * 0.2 + rows * 0.1
                values[:200, :200] = 100.0
                dataset.write(values, 1)

            derive_srtm_terrain(source, target, context)
            with rasterio.open(target) as dataset:
                self.assertEqual(dataset.crs.to_epsg(), 6933)
                self.assertEqual((dataset.height, dataset.width), (260, 260))
                self.assertEqual(dataset.descriptions, SRTM_OUTPUT_BANDS)
                self.assertTrue(numpy.isfinite(dataset.read(1)).all())
                self.assertGreater(float(numpy.nanmean(dataset.read(2))), 0.0)
                consistency = dataset.read(6)
                valid = consistency != dataset.nodata
                self.assertTrue((~valid).any())
                self.assertTrue(
                    ((consistency[valid] >= 0.0) & (consistency[valid] <= 1.0001)).all()
                )
            gdal_dataset = gdal.Open(str(target), gdal.GA_ReadOnly)
            self.assertEqual(
                gdal_dataset.GetMetadata("IMAGE_STRUCTURE").get("LAYOUT"), "COG"
            )
            gdal_dataset = None


if __name__ == "__main__":
    unittest.main()
