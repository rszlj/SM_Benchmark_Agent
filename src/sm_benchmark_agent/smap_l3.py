"""Portable SMAP enhanced L3 V006 native-cell decoding; no imposed quality screening."""
from datetime import date
from pathlib import Path
import re

COLLECTION = 'C2938664763-NSIDC_CPRD'
FIELDS = ('soil_moisture', 'soil_moisture_error', 'retrieval_qual_flag',
          'surface_flag', 'tb_time_seconds', 'EASE_row_index', 'EASE_column_index',
          'latitude', 'longitude', 'tb_h_corrected', 'tb_v_corrected',
          'tb_h_uncorrected', 'tb_v_uncorrected', 'tb_qual_flag_h', 'tb_qual_flag_v')
VARIABLES = tuple(f'Soil_Moisture_Retrieval_Data_{s}/{f}{suffix}'
                  for s, suffix in [('AM',''),('PM','_pm')] for f in FIELDS)
TIME_REFERENCE = 'https://nsidc.org/sites/default/files/d5629220smap20l3_sm_p_e20psd_version2050_final.pdf'


def observation_table(records):
    """Stable nullable column types even for a month with no valid observations."""
    import pyarrow as pa
    integers = {'retrieval_qual_flag', 'surface_flag', 'EASE_row_index',
                'EASE_column_index', 'tb_qual_flag_h', 'tb_qual_flag_v'}
    schema = pa.schema([
        *[(k,pa.string()) for k in ('anchor_id','date','pass')],
        *[(k,pa.int32() if k in integers else pa.float64()) for k in FIELDS],
        ('source_time_units',pa.string()), ('observation_time_utc',pa.string())])
    return pa.Table.from_pylist(records,schema=schema)


def j2000_utc(seconds):
    """PSD section 4.6: seconds since 2000-01-01 12:00:00 TDB, not CF UTC seconds."""
    if seconds is None:
        return None
    from astropy.time import Time, TimeDelta
    from astropy.utils import iers
    iers.conf.auto_download = False
    t = Time('2000-01-01T12:00:00', scale='tdb') + TimeDelta(seconds, format='sec', scale='tdb')
    t.precision = 6
    return t.utc.isot + 'Z'


def decode_subset(path, anchors):
    import h5py
    import numpy as np
    path = Path(path)
    match = re.search(r'SMAP_L3_SM_P_E_(\d{8})_', path.name)
    if not match:
        raise ValueError('Unrecognized SMAP granule name')
    day = date.fromisoformat(match[1]).isoformat()
    records = []
    with h5py.File(path) as f:
        x, y = f['x_global'][()], f['y_global'][()]
        if x.ndim != 1 or y.ndim != 1 or not len(x) or not len(y):
            raise ValueError('Invalid native coordinate axes')
        arrays = {name:f[name][()] for name in VARIABLES}
        for a in anchors:
            j, i = int(np.argmin(abs(x-a.centre_x_m))), int(np.argmin(abs(y-a.centre_y_m)))
            if abs(x[j]-a.centre_x_m)>1 or abs(y[i]-a.centre_y_m)>1:
                raise ValueError('Requested anchor absent from native subset')
            for slot, suffix in [('AM',''),('PM','_pm')]:
                record = {'anchor_id':a.anchor_id, 'date':day, 'pass':slot}
                for field in FIELDS:
                    ds = f[f'Soil_Moisture_Retrieval_Data_{slot}/{field}{suffix}']
                    if ds.shape != (len(y),len(x)):
                        raise ValueError('Unexpected variable dimensions')
                    v = arrays[ds.name.lstrip('/')][i,j].item()
                    fill = ds.attrs.get('_FillValue')
                    record[field] = None if (fill is not None and v == fill) or not np.isfinite(v) else v
                for field, expected in [('EASE_row_index',a.row),('EASE_column_index',a.column)]:
                    if record[field] is not None and record[field] != expected:
                        raise ValueError('Native row/column mismatch')
                if record['soil_moisture'] is not None and any(record[k] is None for k in ['EASE_row_index','EASE_column_index']):
                    raise ValueError('Soil moisture present without source cell identity')
                ds = f[f'Soil_Moisture_Retrieval_Data_{slot}/tb_time_seconds{suffix}']
                units = ds.attrs['units']
                record['source_time_units'] = units.decode() if isinstance(units,bytes) else str(units)
                if record['source_time_units'] != 'seconds since 2000-01-01 11:58:55.816Z':
                    raise ValueError('Unexpected time metadata; review before conversion')
                record['observation_time_utc'] = j2000_utc(record['tb_time_seconds'])
                records.append(record)
    return records
