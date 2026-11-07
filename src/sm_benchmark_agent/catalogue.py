"""Read-only catalogue API. All locations are relative to a supplied release."""
import csv
import gzip
import json
from pathlib import Path

from .archives import safe_relative

SOURCE_COLUMNS = {
    'srtm': 'srtm', 'hwsd2': 'hwsd2', 'mcd12q1': 'mcd12q1_lulc',
    'mod13q1_ndvi': 'mod13q1_ndvi', 'myd13q1_ndvi': 'myd13q1_ndvi',
    'mod11a2_lst': 'mod11a2_lst', 'myd11a2_lst': 'myd11a2_lst',
    'sentinel1': 'sentinel1', 'era5_land': 'era5_land', 'gldas21': 'gldas21',
    'imerg_v07': 'imerg_v07', 'smap_l4': 'smap_l4', 'ismn': None,
}


class ReleaseCatalogue:
    def __init__(self, root, *, package_root=None, station_inventory=None):
        self.root = Path(root).resolve()
        self.package_root = Path(package_root).resolve() if package_root is not None else self.root
        if any('obsolete' in part.lower() for part in (*self.root.parts, *self.package_root.parts)):
            raise ValueError('Obsolete releases are not delivery sources')
        self.release = json.loads((self.root / 'release.json').read_text(encoding='utf-8'))
        self.rows = {}
        with gzip.open(self.root / 'catalog.csv.gz', 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                key = row['anchor_id'], int(row['year'])
                if key in self.rows:
                    raise ValueError('Duplicate catalogue anchor-year')
                self.rows[key] = row
        self.station_inventory_anchors = None
        if station_inventory is not None:
            with Path(station_inventory).open(encoding='utf-8', newline='') as stream:
                self.station_inventory_anchors = sorted({r['anchor_id'] for r in csv.DictReader(stream)})

    @property
    def package_anchors(self):
        return sorted({a for (a, _), row in self.rows.items() if row['build_status'] == 'complete'})

    def package_years(self, anchor_id):
        return sorted(y for (a, y), row in self.rows.items()
                      if a == anchor_id and row['build_status'] == 'complete')

    def package(self, anchor_id, year):
        row = self.rows.get((anchor_id, year))
        return dict(row) if row is not None else None

    def archive_path(self, row):
        relative = safe_relative(row['archive_path'])
        path = self.package_root.joinpath(*relative.parts).resolve()
        if not path.is_relative_to(self.package_root) or any('obsolete' in p.lower() for p in path.parts):
            raise ValueError('Archive escapes valid release')
        return path

    def availability(self, anchor_id, year, source):
        if source not in SOURCE_COLUMNS:
            raise ValueError('Unsupported registered source: ' + source)
        row = self.rows.get((anchor_id, year))
        raw = (('available' if row.get('station_count', '0') != '0' else 'not processed')
               if source == 'ismn' else row.get(SOURCE_COLUMNS[source], 'not processed')) if row else 'not processed'
        state = 'unavailable' if raw in {'unavailable_by_design', 'unavailable_archive'} else raw
        if state not in {'available', 'partial', 'unavailable', 'not processed', 'failed'}:
            raise ValueError('Unknown catalogue availability state: ' + state)
        return {'state': state, 'reason': raw if state != 'available' else None}
