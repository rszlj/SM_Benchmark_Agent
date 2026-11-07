from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sm_benchmark_agent.grid import ContextResolution, anchor_cell, context_grid
from sm_benchmark_agent.processing.lst import derive_mod11a2_lst


class MOD11A2LSTTests(unittest.TestCase):
    def test_derives_paired_celsius_stacks(self) -> None:
        import numpy
        import rasterio
        from rasterio.transform import from_bounds

        context = context_grid(
            anchor_cell(-86.9023, 32.3182), ContextResolution("1 km", 1)
        )
        dates = {
            "2000_2007": ["2000-02-18", "2000-02-26"],
            "2008_2015": ["2008-01-01"],
            "2016_2025": ["2016-01-01"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = {}
            for chunk, chunk_dates in dates.items():
                path = root / f"{chunk}.tif"
                raw[chunk] = path
                with rasterio.open(
                    path, "w", driver="GTiff", width=20, height=20,
                    count=2 * len(chunk_dates), dtype="int16", crs="EPSG:6933",
                    transform=from_bounds(
                        context.bounds.xmin, context.bounds.ymin,
                        context.bounds.xmax, context.bounds.ymax, 20, 20,
                    ), nodata=-32768,
                ) as source:
                    for index in range(len(chunk_dates)):
                        day_values = numpy.full((20, 20), 15000, dtype="int16")
                        day_values[0, 0] = -32768
                        source.write(day_values, 2 * index + 1)
                        source.write(numpy.full((20, 20), 14000, dtype="int16"), 2 * index + 2)
            result = derive_mod11a2_lst(
                raw_chunks=raw, dates_by_chunk=dates, context=context,
                output_root=root / "output", source_crs=None,
                working_root=root / "scratch",
            )
            self.assertEqual(result["status"], "derived")
            with rasterio.open(result["day"]) as output:
                self.assertEqual((output.count, output.height, output.width), (4, 13, 13))
                self.assertEqual(output.crs.to_epsg(), 6933)
                values = output.read(1)
                valid = values[values != output.nodata]
                self.assertAlmostEqual(float(valid.mean()), 26.85, places=3)
                self.assertEqual(output.descriptions[0], "2000-02-18")
                self.assertGreater(valid.min(), -200.0)
            with rasterio.open(result["night"]) as output:
                self.assertAlmostEqual(float(output.read(1).mean()), 6.85, places=3)
            import json
            aqua_raw = dict(raw)
            aqua_raw["2002_2007"] = aqua_raw.pop("2000_2007")
            aqua_dates = dict(dates)
            aqua_dates.pop("2000_2007")
            aqua_dates["2002_2007"] = ["2002-07-04", "2002-07-12"]
            aqua = derive_mod11a2_lst(
                raw_chunks=aqua_raw, dates_by_chunk=aqua_dates, context=context,
                output_root=root / "output", source_crs=None,
                working_root=root / "scratch", product="myd11a2",
            )
            self.assertNotEqual(result["day"], aqua["day"])
            with rasterio.open(aqua["day"]) as output:
                self.assertEqual(output.tags()["platform"], "Aqua")
                self.assertEqual(output.tags()["collection"], "MODIS/061/MYD11A2")
                self.assertEqual(output.tags(1)["platform"], "Aqua")
                self.assertEqual(output.descriptions[0], "2002-07-04")
                valid=output.read(1, masked=True)
                self.assertAlmostEqual(float(valid.mean()), 26.85, places=3)
            metadata=json.loads(Path(aqua["manifest"]).read_text())
            self.assertEqual(metadata["platform"], "Aqua")
            self.assertEqual(metadata["dates"], ["2002-07-04", "2002-07-12", "2008-01-01", "2016-01-01"])


if __name__ == "__main__":
    unittest.main()
