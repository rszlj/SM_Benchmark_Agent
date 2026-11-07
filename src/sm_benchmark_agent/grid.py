"""EASE-Grid 2.0 anchor cells and aligned multiresolution contexts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache

from pyproj import CRS, Transformer


EASE2_GLOBAL_EPSG = 6933
EASE2_GLOBAL_X_MIN_M = -17367530.4451615
EASE2_GLOBAL_Y_MAX_M = 7314540.8306386
EASE2_M09KM_SPACING_M = 9008.055210146
NSIDC_GRID_DEFINITION_SOURCE = "https://github.com/nsidc/mapxmaps"
EASE2_M09KM_ANCHOR_PATTERN = re.compile(
    r"^EASE2_M09km_R(?P<row>\d{4})_C(?P<column>\d{4})$"
)


@dataclass(frozen=True, slots=True)
class ProjectedBounds:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin


@dataclass(frozen=True, slots=True)
class GridDefinition:
    grid_id: str
    nominal_resolution: str
    exact_spacing_m: float
    columns: int
    rows: int
    upper_left_x_m: float = EASE2_GLOBAL_X_MIN_M
    upper_left_y_m: float = EASE2_GLOBAL_Y_MAX_M
    crs_epsg: int = EASE2_GLOBAL_EPSG
    definition_source: str = NSIDC_GRID_DEFINITION_SOURCE

    @property
    def bounds(self) -> ProjectedBounds:
        return ProjectedBounds(
            xmin=self.upper_left_x_m,
            ymin=self.upper_left_y_m - self.rows * self.exact_spacing_m,
            xmax=self.upper_left_x_m + self.columns * self.exact_spacing_m,
            ymax=self.upper_left_y_m,
        )

    @property
    def crs_wkt(self) -> str:
        return CRS.from_epsg(self.crs_epsg).to_wkt()


@dataclass(frozen=True, slots=True)
class AnchorCell:
    anchor_id: str
    row: int
    column: int
    centre_x_m: float
    centre_y_m: float
    centre_longitude: float
    centre_latitude: float
    bounds: ProjectedBounds
    grid: GridDefinition


@dataclass(frozen=True, slots=True)
class ContextResolution:
    nominal_resolution: str
    subdivisions_per_1km_cell: int

    def __post_init__(self) -> None:
        if not self.nominal_resolution.strip():
            raise ValueError("nominal_resolution cannot be empty")
        if self.subdivisions_per_1km_cell < 1:
            raise ValueError("subdivisions_per_1km_cell must be at least 1")


@dataclass(frozen=True, slots=True)
class ContextGrid:
    anchor_id: str
    nominal_resolution: str
    exact_spacing_m: float
    columns: int
    rows: int
    upper_left_x_m: float
    upper_left_y_m: float
    bounds: ProjectedBounds
    alignment_grid_id: str
    crs_epsg: int = EASE2_GLOBAL_EPSG

    @property
    def crs_wkt(self) -> str:
        return CRS.from_epsg(self.crs_epsg).to_wkt()


@lru_cache(maxsize=1)
def ease2_global_grids() -> dict[str, GridDefinition]:
    """Return the established nested global 1/3/9/36 km definitions."""

    spacing_1km = EASE2_M09KM_SPACING_M / 9
    return {
        "EASE2_M01km": GridDefinition(
            "EASE2_M01km", "1 km", spacing_1km, 34704, 14616
        ),
        "EASE2_M03km": GridDefinition(
            "EASE2_M03km", "3 km", EASE2_M09KM_SPACING_M / 3, 11568, 4872
        ),
        "EASE2_M09km": GridDefinition(
            "EASE2_M09km", "9 km", EASE2_M09KM_SPACING_M, 3856, 1624
        ),
        "EASE2_M36km": GridDefinition(
            "EASE2_M36km", "36 km", EASE2_M09KM_SPACING_M * 4, 964, 406
        ),
    }


@lru_cache(maxsize=1)
def _forward_transformer() -> Transformer:
    return Transformer.from_crs(4326, EASE2_GLOBAL_EPSG, always_xy=True)


@lru_cache(maxsize=1)
def _inverse_transformer() -> Transformer:
    return Transformer.from_crs(EASE2_GLOBAL_EPSG, 4326, always_xy=True)


def _cell_index(value: float, start: float, spacing: float, count: int) -> int:
    index = math.floor((value - start) / spacing)
    upper = start + count * spacing
    if index == count and math.isclose(value, upper, abs_tol=1e-7):
        return count - 1
    if not 0 <= index < count:
        raise ValueError("coordinate falls outside the EASE2 global grid")
    return index


def anchor_cell(longitude: float, latitude: float) -> AnchorCell:
    """Map a WGS84 location to its zero-based global nominal-9-km anchor."""

    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("invalid WGS84 longitude or latitude")
    grid = ease2_global_grids()["EASE2_M09km"]
    x, y = _forward_transformer().transform(longitude, latitude)
    column = _cell_index(x, grid.upper_left_x_m, grid.exact_spacing_m, grid.columns)
    row = _cell_index(grid.upper_left_y_m - y, 0.0, grid.exact_spacing_m, grid.rows)
    xmin = grid.upper_left_x_m + column * grid.exact_spacing_m
    ymax = grid.upper_left_y_m - row * grid.exact_spacing_m
    bounds = ProjectedBounds(
        xmin=xmin,
        ymin=ymax - grid.exact_spacing_m,
        xmax=xmin + grid.exact_spacing_m,
        ymax=ymax,
    )
    centre_x = (bounds.xmin + bounds.xmax) / 2
    centre_y = (bounds.ymin + bounds.ymax) / 2
    centre_lon, centre_lat = _inverse_transformer().transform(centre_x, centre_y)
    return AnchorCell(
        anchor_id=f"EASE2_M09km_R{row:04d}_C{column:04d}",
        row=row,
        column=column,
        centre_x_m=centre_x,
        centre_y_m=centre_y,
        centre_longitude=centre_lon,
        centre_latitude=centre_lat,
        bounds=bounds,
        grid=grid,
    )


def anchor_cell_from_id(anchor_id: str) -> AnchorCell:
    """Reconstruct a nominal-9-km anchor from its stable zero-based ID."""

    match = EASE2_M09KM_ANCHOR_PATTERN.fullmatch(anchor_id)
    if match is None:
        raise ValueError(f"invalid EASE2_M09km anchor ID: {anchor_id}")
    row = int(match.group("row"))
    column = int(match.group("column"))
    grid = ease2_global_grids()["EASE2_M09km"]
    if not 0 <= row < grid.rows or not 0 <= column < grid.columns:
        raise ValueError(f"anchor ID falls outside EASE2_M09km: {anchor_id}")
    xmin = grid.upper_left_x_m + column * grid.exact_spacing_m
    ymax = grid.upper_left_y_m - row * grid.exact_spacing_m
    bounds = ProjectedBounds(
        xmin=xmin,
        ymin=ymax - grid.exact_spacing_m,
        xmax=xmin + grid.exact_spacing_m,
        ymax=ymax,
    )
    centre_x = (bounds.xmin + bounds.xmax) / 2
    centre_y = (bounds.ymin + bounds.ymax) / 2
    centre_lon, centre_lat = _inverse_transformer().transform(centre_x, centre_y)
    return AnchorCell(
        anchor_id=anchor_id,
        row=row,
        column=column,
        centre_x_m=centre_x,
        centre_y_m=centre_y,
        centre_longitude=centre_lon,
        centre_latitude=centre_lat,
        bounds=bounds,
        grid=grid,
    )


def context_grid(anchor: AnchorCell, resolution: ContextResolution) -> ContextGrid:
    """Create an equivalent-bounds context aligned to the nominal 1 km grid."""

    base = ease2_global_grids()["EASE2_M01km"]
    factor = resolution.subdivisions_per_1km_cell
    spacing = base.exact_spacing_m / factor
    columns = rows = 13 * factor
    half_extent = 13 * base.exact_spacing_m / 2
    bounds = ProjectedBounds(
        xmin=anchor.centre_x_m - half_extent,
        ymin=anchor.centre_y_m - half_extent,
        xmax=anchor.centre_x_m + half_extent,
        ymax=anchor.centre_y_m + half_extent,
    )
    return ContextGrid(
        anchor_id=anchor.anchor_id,
        nominal_resolution=resolution.nominal_resolution,
        exact_spacing_m=spacing,
        columns=columns,
        rows=rows,
        upper_left_x_m=bounds.xmin,
        upper_left_y_m=bounds.ymax,
        bounds=bounds,
        alignment_grid_id=base.grid_id,
    )
