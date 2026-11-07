"""Inclusive UTC date requests; provider bounds are half-open intervals."""
from datetime import date, datetime, timedelta, timezone


def bounds(unit):
    if (unit.start is None) != (unit.end is None):
        raise ValueError('Both period dates are required')
    if unit.start is None:
        return datetime(unit.year, 1, 1, tzinfo=timezone.utc), datetime(unit.year+1, 1, 1, tzinfo=timezone.utc)
    start, end = date.fromisoformat(unit.start), date.fromisoformat(unit.end)
    if start.isoformat()!=unit.start or end.isoformat()!=unit.end or start > end or start.year!=unit.year or end.year!=unit.year:
        raise ValueError('Source unit dates must be canonical, ordered and within its year')
    return datetime.combine(start, datetime.min.time(), timezone.utc), datetime.combine(end+timedelta(days=1), datetime.min.time(), timezone.utc)


def months(unit):
    start, end = bounds(unit)
    return range(start.month, (end-timedelta(microseconds=1)).month+1)


def month_bounds(unit, month):
    start, end = bounds(unit)
    return max(start, datetime(unit.year,month,1,tzinfo=timezone.utc)), min(end, datetime(unit.year+(month==12),month%12+1,1,tzinfo=timezone.utc))


def suffix(unit):
    bounds(unit)
    return '' if unit.start is None else f'/period-{unit.start}_{unit.end}'


def metadata(unit):
    bounds(unit)
    return {} if unit.start is None else {'requested_period': {'start':unit.start,'end':unit.end,'timezone':'UTC','end_inclusive':True},
        'temporal_selection':'source timestamp or composite start in requested interval; original temporal support retained'}


def contains(unit, stamp):
    start,end=bounds(unit)
    return start<=stamp<end
