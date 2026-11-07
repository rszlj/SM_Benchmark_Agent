"""V1 profile constants migrated from the recorded production sources."""

ERA5_MAP = {'2m_temperature': 'temperature_2m', 'skin_temperature': 'skin_temperature', 'surface_pressure': 'surface_pressure', '10m_u_component_of_wind': 'u_component_of_wind_10m', '10m_v_component_of_wind': 'v_component_of_wind_10m', 'total_precipitation': 'total_precipitation', 'volumetric_soil_water_layer_1': 'volumetric_soil_water_layer_1', 'surface_runoff': 'surface_runoff', 'potential_evaporation': 'potential_evaporation', 'total_evaporation': 'total_evaporation', 'forecast_albedo': 'forecast_albedo', 'soil_temperature_level_1': 'soil_temperature_level_1', 'surface_latent_heat_flux': 'surface_latent_heat_flux', 'surface_sensible_heat_flux': 'surface_sensible_heat_flux', 'surface_solar_radiation_downwards': 'surface_solar_radiation_downwards', 'surface_thermal_radiation_downwards': 'surface_thermal_radiation_downwards', 'surface_net_solar_radiation': 'surface_net_solar_radiation', 'surface_net_thermal_radiation': 'surface_net_thermal_radiation'}

ERA5_TRANSFORM = (0.1, 0.0, -180.05, 0.0, -0.1, 90.05)

ERA5_UNITS = {'2m_temperature': 'K', 'skin_temperature': 'K', 'surface_pressure': 'Pa', '10m_u_component_of_wind': 'm s-1', '10m_v_component_of_wind': 'm s-1', 'total_precipitation': 'm', 'volumetric_soil_water_layer_1': 'm3 m-3', 'surface_runoff': 'm', 'potential_evaporation': 'm', 'total_evaporation': 'm water equivalent', 'forecast_albedo': '1', 'soil_temperature_level_1': 'K', 'surface_latent_heat_flux': 'J m-2', 'surface_sensible_heat_flux': 'J m-2', 'surface_solar_radiation_downwards': 'J m-2', 'surface_thermal_radiation_downwards': 'J m-2', 'surface_net_solar_radiation': 'J m-2', 'surface_net_thermal_radiation': 'J m-2'}

IMERG_BANDS = ('MWobservationTime', 'MWprecipSource', 'MWprecipitation', 'IRinfluence', 'IRprecipitation', 'precipitation', 'precipitationUncal', 'probabilityLiquidPrecipitation', 'randomError')

IMERG_UNITS = {'MWobservationTime': 'minutes into half hour', 'MWprecipSource': 'sensor identifier', 'MWprecipitation': 'mm h-1', 'IRinfluence': '%', 'IRprecipitation': 'mm h-1', 'precipitation': 'mm h-1', 'precipitationUncal': 'mm h-1', 'probabilityLiquidPrecipitation': '%', 'randomError': 'mm h-1'}

IMERG_TRANSFORM = (0.1, 0.0, -180.0, 0.0, -0.1, 90.0)

IMERG_SENTINEL = -9999.0
