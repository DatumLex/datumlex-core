"""Shared lower boundary for historical DataJud queries and dashboard filters."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

EARLIEST_DATE = date(2010, 1, 1)
EARLIEST_DATE_ISO = EARLIEST_DATE.isoformat()
HISTORY_START = date(2016, 1, 1)


def today():
    return datetime.now(ZoneInfo('America/Sao_Paulo')).date()
