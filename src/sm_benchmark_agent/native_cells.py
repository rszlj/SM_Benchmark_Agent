"""Offline native-cell geometry shared by public planning and provider adapters."""

def era5_land_native_cell(
    longitude: float, latitude: float
) -> dict[str, float | int]:
    """Return the native ERA5-Land cell containing a coordinate."""

    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("longitude/latitude outside the ERA5-Land grid")
    column = min(3600, int((longitude + 180.05) // 0.1))
    row = min(1800, int((90.05 - latitude) // 0.1))
    return {
        "row": row,
        "column": column,
        "centre_longitude": round(-180.05 + (column + 0.5) * 0.1, 10),
        "centre_latitude": round(90.05 - (row + 0.5) * 0.1, 10),
    }


def gldas21_native_cell(longitude: float, latitude: float) -> dict[str, float | int]:
    """Return the native 0.25-degree cell containing a coordinate."""

    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("longitude/latitude outside the GLDAS grid")
    column = min(1439, int((longitude + 180.0) // 0.25))
    row = min(719, int((90.0 - latitude) // 0.25))
    return {
        "row": row,
        "column": column,
        "centre_longitude": -180.0 + (column + 0.5) * 0.25,
        "centre_latitude": 90.0 - (row + 0.5) * 0.25,
    }


def imerg_v07_native_cell(longitude: float, latitude: float) -> dict[str, float | int]:
    """Return the native 0.1-degree cell containing a coordinate."""

    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("longitude/latitude outside the IMERG grid")
    column = min(3599, int((longitude + 180.0) // 0.1))
    row = min(1799, int((90.0 - latitude) // 0.1))
    return {
        "row": row,
        "column": column,
        "centre_longitude": round(-180.0 + (column + 0.5) * 0.1, 10),
        "centre_latitude": round(90.0 - (row + 0.5) * 0.1, 10),
    }
