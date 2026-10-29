"""Shared lower boundary for historical DataJud queries and dashboard filters."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

EARLIEST_DATE = date(2016, 1, 1)
EARLIEST_DATE_ISO = EARLIEST_DATE.isoformat()
HISTORY_START = EARLIEST_DATE


def today():
    return datetime.now(ZoneInfo('America/Sao_Paulo')).date()
