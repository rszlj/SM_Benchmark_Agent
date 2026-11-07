from __future__ import annotations

import unittest

from sm_benchmark_agent.grid import (
    ContextResolution,
    anchor_cell,
    context_grid,
    ease2_global_grids,
)


class GridRegistryTests(unittest.TestCase):
    def test_authoritative_global_definitions_and_nesting(self) -> None:
        grids = ease2_global_grids()
        one = grids["EASE2_M01km"]
        three = grids["EASE2_M03km"]
        nine = grids["EASE2_M09km"]
        thirty_six = grids["EASE2_M36km"]

        self.assertEqual((nine.columns, nine.rows), (3856, 1624))
        self.assertEqual(nine.crs_epsg, 6933)
        self.assertEqual(one.exact_spacing_m * 9, nine.exact_spacing_m)
        self.assertEqual(three.exact_spacing_m * 3, nine.exact_spacing_m)
        self.assertEqual(nine.exact_spacing_m * 4, thirty_six.exact_spacing_m)
        self.assertNotEqual(one.nominal_resolution, str(one.exact_spacing_m))

    def test_equator_prime_meridian_has_stable_zero_based_identifier(self) -> None:
        anchor = anchor_cell(0.0, 0.0)
        self.assertEqual(anchor.anchor_id, "EASE2_M09km_R0812_C1928")
        self.assertEqual((anchor.row, anchor.column), (812, 1928))

    def test_alabama_anchor_is_stable(self) -> None:
        anchor = anchor_cell(147.53480, -35.32395)
        self.assertEqual(anchor.anchor_id, "EASE2_M09km_R1281_C3508")

    def test_nominal_one_km_context_is_13_by_13_and_centred(self) -> None:
        anchor = anchor_cell(147.53480, -35.32395)
        context = context_grid(anchor, ContextResolution("1 km", 1))
        self.assertEqual((context.rows, context.columns), (13, 13))
        self.assertAlmostEqual(
            (context.bounds.xmin + context.bounds.xmax) / 2,
            anchor.centre_x_m,
        )
        self.assertAlmostEqual(
            (context.bounds.ymin + context.bounds.ymax) / 2,
            anchor.centre_y_m,
        )
        base = ease2_global_grids()["EASE2_M01km"]
        left_index = (context.bounds.xmin - base.upper_left_x_m) / base.exact_spacing_m
        top_index = (base.upper_left_y_m - context.bounds.ymax) / base.exact_spacing_m
        self.assertAlmostEqual(left_index, round(left_index))
        self.assertAlmostEqual(top_index, round(top_index))

    def test_nominal_250_m_context_has_equivalent_bounds(self) -> None:
        anchor = anchor_cell(147.53480, -35.32395)
        one_km = context_grid(anchor, ContextResolution("1 km", 1))
        quarter = context_grid(anchor, ContextResolution("250 m", 4))
        self.assertEqual((quarter.rows, quarter.columns), (52, 52))
        self.assertEqual(quarter.bounds, one_km.bounds)
        self.assertEqual(quarter.exact_spacing_m * 4, one_km.exact_spacing_m)

    def test_polar_location_outside_global_grid_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside"):
            anchor_cell(0.0, 90.0)


if __name__ == "__main__":
    unittest.main()
