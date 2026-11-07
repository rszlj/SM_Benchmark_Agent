"""Annual LC_Type1 derivation migrated from the V1 2025 preparation route.

Year is parameterized. Nearest-neighbour reprojection and class masks are kept;
public float32/NaN conversion is performed separately after derivation.
"""
from pathlib import Path

COLLECTION = 'MODIS/061/MCD12Q1'
NATIVE_CRS = '+proj=sinu +R=6371007.181 +nadgrids=@null +wktext'


def derive_landcover(payload, target, context, year):
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from rasterio.warp import reproject, Resampling
    if context.rows != 26 or context.columns != 26 or context.nominal_resolution != '500 m':
        raise ValueError('Land cover requires the canonical 500 m context')
    if Path(target).exists():
        raise FileExistsError('Land-cover output already exists')
    transform = from_origin(context.upper_left_x_m, context.upper_left_y_m,
                            context.exact_spacing_m, context.exact_spacing_m)
    with MemoryFile(payload) as memory, memory.open() as source:
        if source.count != 1 or source.crs is None:
            raise ValueError('Expected one georeferenced LC_Type1 band')
        values = source.read(1)
        normalized = np.where((values >= 1) & (values <= 17), values, 255).astype('uint8')
        destination = np.full((26, 26), 255, dtype='uint8')
        reproject(source=normalized, destination=destination,
                  src_transform=source.transform, src_crs=source.crs, src_nodata=255,
                  dst_transform=transform, dst_crs='EPSG:6933', dst_nodata=255,
                  resampling=Resampling.nearest)
    with rasterio.open(target, 'w', driver='GTiff', width=26, height=26, count=1,
                       dtype='uint8', crs='EPSG:6933', transform=transform,
                       nodata=255, compress='deflate') as output:
        output.write(destination, 1)
        output.set_band_description(1, f'{year}_LC_Type1')
        output.update_tags(collection=COLLECTION, year=str(year), classification='IGBP',
                           valid_classes='1-17', resampling='nearest')
        output.update_tags(1, year=str(year), variable='LC_Type1', classification='IGBP')


def public_raster(source, target):
    """Use the V1 mask conversion; never mask by arbitrary numeric equality."""
    import numpy as np
    import rasterio
    from ..gldas_workflow import check_public_metadata
    with rasterio.open(source) as src:
        profile = src.profile.copy()
        profile.update(dtype='float32', nodata=np.nan, predictor=3)
        with rasterio.open(target, 'w', **profile) as dst:
            dst.write(src.read(masked=True).astype('float32').filled(np.nan))
            # Retain scientific tags only; private acquisition manifests are not copied.
            allowed = {'terrain_algorithm', 'aspect_convention', 'aspect_aggregation',
                       'working_crs', 'working_resolution_m', 'resampling', 'collection',
                       'year', 'classification', 'valid_classes', 'component_aggregation',
                       'layer', 'top_depth_cm', 'bottom_depth_cm', 'property', 'unit',
                       'description', 'variable', 'timestamp_utc', 'platform',
                       'source_scale_factor_applied', 'temporal_sampling',
                       'composite_start', 'source_scale', 'source_offset', 'source_crs_override'}
            for band in range(src.count + 1):
                tags = {k: v for k, v in src.tags(band).items() if k in allowed}
                check_public_metadata(tags)
                dst.update_tags(band, **tags)
                if band and src.descriptions[band - 1]:
                    dst.set_band_description(band, src.descriptions[band - 1])
