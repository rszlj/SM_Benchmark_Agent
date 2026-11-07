"""V1 corrected Aqua NDVI: authoritative CRS and normalized convolution.

Migrated from rebuild_myd13q1_from_local_raw.py, parameterized for one year.
Terra retains its separate V1 preparation path.
"""
from datetime import datetime, timezone
from pathlib import Path

from .landcover import NATIVE_CRS
from .ndvi import (MOD13Q1_NDVI_VALID_MIN, MOD13Q1_NDVI_VALID_MAX,
                   MOD13Q1_NDVI_SCALE, MOD13Q1_NDVI_OUTPUT_NODATA, _validate_context)


def derive_aqua_ndvi(payload, target, context, dates):
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from rasterio.warp import reproject, Resampling
    _validate_context(context)
    if not dates or dates != sorted(set(dates)) or any(d.year != dates[0].year for d in dates):
        raise ValueError('Aqua requires ordered unique dates within one year')
    if Path(target).exists():
        raise FileExistsError('Aqua output already exists')
    transform = from_origin(context.upper_left_x_m, context.upper_left_y_m,
                            context.exact_spacing_m, context.exact_spacing_m)
    with MemoryFile(payload) as memory, memory.open() as source:
        if source.count != len(dates) or source.crs is None:
            raise ValueError('Aqua raw band/date/CRS mismatch')
        raw_values = source.read().astype('float32')
        valid = np.isfinite(raw_values) & (raw_values >= MOD13Q1_NDVI_VALID_MIN) & (raw_values <= MOD13Q1_NDVI_VALID_MAX)
        numerator_source = np.where(valid, raw_values * MOD13Q1_NDVI_SCALE, 0.0).astype('float32')
        weight_source = valid.astype('float32')
        numerator = np.zeros((len(dates), context.rows, context.columns), dtype='float32')
        weights = np.zeros_like(numerator)
        for values, destination in ((numerator_source, numerator), (weight_source, weights)):
            reproject(source=values, destination=destination, src_transform=source.transform,
                      src_crs=NATIVE_CRS, dst_transform=transform, dst_crs='EPSG:6933',
                      resampling=Resampling.bilinear)
        result = np.full_like(numerator, MOD13Q1_NDVI_OUTPUT_NODATA)
        covered = weights > 1e-6
        result[covered] = numerator[covered] / weights[covered]
    with rasterio.open(target, 'w', driver='GTiff', width=context.columns, height=context.rows,
                       count=len(dates), dtype='float32', crs='EPSG:6933', transform=transform,
                       nodata=MOD13Q1_NDVI_OUTPUT_NODATA, compress='deflate', predictor=3,
                       tiled=True, blockxsize=256, blockysize=256, interleave='band') as output:
        output.write(result)
        for band, stamp in enumerate(dates, 1):
            output.set_band_description(band, f'{stamp.isoformat()}_Aqua')
            output.update_tags(band, timestamp_utc=datetime.combine(stamp, datetime.min.time(), timezone.utc).isoformat(),
                               platform='Aqua', source_scale_factor_applied=str(MOD13Q1_NDVI_SCALE))
        output.update_tags(collection='MODIS/061/MYD13Q1', variable='NDVI',
                           temporal_sampling='16-day composite', resampling='bilinear', source_crs_override=NATIVE_CRS)
