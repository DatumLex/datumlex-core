"""Keep one read snapshot when an export owns its database transaction."""

from contextlib import contextmanager

from django.db import connection, transaction


@contextmanager
def report_transaction():
    outermost = not connection.in_atomic_block and connection.get_autocommit()
    with transaction.atomic():
        if outermost and connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield
