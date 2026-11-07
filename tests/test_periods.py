from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sm_benchmark_agent import periods
from sm_benchmark_agent.adapters import SourceUnit
from sm_benchmark_agent.smap_sources import SMAPL4Adapter, PROFILES, calendar_times


class PeriodTests(unittest.TestCase):
    def unit(self, start, end, year=2016):
        return SourceUnit('smap_l4',PROFILES['smap_l4'],'EASE2_M09km_R0403_C0871',year,start,end)

    def test_leap_day_and_clipped_month_edges(self):
        unit=self.unit('2016-02-29','2016-03-02')
        self.assertEqual(list(periods.months(unit)),[2,3])
        self.assertEqual(periods.month_bounds(unit,2)[0],datetime(2016,2,29,tzinfo=timezone.utc))
        self.assertEqual(periods.month_bounds(unit,3)[1],datetime(2016,3,3,tzinfo=timezone.utc))
        self.assertEqual(len(calendar_times(unit)),24)

    def test_invalid_dates_and_cross_year_units_rejected(self):
        for start,end in [('2016-02-30','2016-03-01'),('2016-03-01','2016-02-01'),
                          ('2015-12-31','2016-01-01'),('2016-01-01',None),('20160101','2016-01-01')]:
            with self.assertRaises((ValueError,TypeError)):
                periods.bounds(self.unit(start,end))

    def test_before_product_start_never_queries_reversed_interval(self):
        unit=self.unit('2015-03-01','2015-03-30',2015)
        with tempfile.TemporaryDirectory() as temp, patch('socket.socket',side_effect=AssertionError('No network')):
            adapter=SMAPL4Adapter()
            plan=adapter.plan(unit,asset_root=Path(temp))
            self.assertEqual(plan.state,'unavailable')
            self.assertEqual(plan.remote_operations,0)
            self.assertEqual(calendar_times(unit),[])
