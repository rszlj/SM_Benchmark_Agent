"""V1 SMAP v007 bands and calendar migrated from the established decoder."""
import calendar
from datetime import datetime, timedelta, timezone

SMAP_L4_SOURCE_ID = "NASA/SMAP/SPL4SMGP/007"

SMAP_L4_STEP = timedelta(hours=3)

SMAP_L4_BANDS = (
    "baseflow_flux",
    "depth_to_water_table_from_surface_in_peat",
    "free_surface_water_on_peat_flux",
    "heat_flux_ground",
    "heat_flux_latent",
    "heat_flux_sensible",
    "height_lowatmmodlay",
    "land_evapotranspiration_flux",
    "land_fraction_saturated",
    "land_fraction_snow_covered",
    "land_fraction_unsaturated",
    "land_fraction_wilting",
    "leaf_area_index",
    "mwrtm_vegopacity",
    "net_downward_longwave_flux",
    "net_downward_shortwave_flux",
    "overland_runoff_flux",
    "precipitation_total_surface_flux",
    "radiation_longwave_absorbed_flux",
    "radiation_shortwave_downward_flux",
    "sm_profile",
    "sm_profile_pctl",
    "sm_profile_wetness",
    "sm_rootzone",
    "sm_rootzone_pctl",
    "sm_rootzone_wetness",
    "sm_surface",
    "sm_surface_wetness",
    "snow_depth",
    "snow_mass",
    "snow_melt_flux",
    "soil_temp_layer1",
    "soil_temp_layer2",
    "soil_temp_layer3",
    "soil_temp_layer4",
    "soil_temp_layer5",
    "soil_temp_layer6",
    "soil_water_infiltration_flux",
    "specific_humidity_lowatmmodlay",
    "surface_pressure",
    "surface_temp",
    "temp_lowatmmodlay",
    "vegetation_greenness_fraction",
    "windspeed_lowatmmodlay",
    "snowfall_surface_flux",
)

def expected_smap_l4_month_times(year: int, month: int) -> tuple[datetime, ...]:
    """Return the exact 3-hour UTC calendar expected in one NAS month."""

    if year < 2015 or month not in range(1, 13):
        raise ValueError("SMAP L4 month must be March 2015 or later")
    if (year, month) < (2015, 3):
        raise ValueError("SMAP L4 begins in March 2015")
    if (year, month) == (2015, 3):
        start = datetime(2015, 3, 31, 1, 30, tzinfo=timezone.utc)
        day_count = 1
    else:
        start = datetime(year, month, 1, 1, 30, tzinfo=timezone.utc)
        day_count = calendar.monthrange(year, month)[1]
    count = day_count * 8
    return tuple(start + index * SMAP_L4_STEP for index in range(count))
