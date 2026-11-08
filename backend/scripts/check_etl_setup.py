"""Check clone-local ETL prerequisites without collecting data or migrating."""
import json
from pathlib import Path
import os
import shutil
import sys
from datetime import datetime, timezone
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent / 'tools/nlp_validation'))
from etl_runtime import atomic_json


def check():
    if not (BACKEND / '.env').is_file():
        raise ValueError('Create backend/.env with scripts/setup.ps1 first')
    import django
    import pypdf  # noqa: F401
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()
    from django.conf import settings
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    database = settings.DATABASES['default']
    engine = database['ENGINE']
    if engine == 'django.db.backends.sqlite3':
        name = str(database['NAME'])
        if name == ':memory:' or not Path(name).is_file():
            raise ValueError('Prepare the persistent database with scripts/setup.ps1 -Migrate')
    elif engine != 'django.db.backends.postgresql' or database.get('HOST') not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('ETL automation requires SQLite or a loopback PostgreSQL database')
    if shutil.disk_usage(settings.DATA_DIR).free < 1_000_000_000:
        raise ValueError('At least 1 GB of free storage is required')
    connection.ensure_connection()
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise ValueError('Apply pending migrations with scripts/setup.ps1 -Migrate -SkipDependencies')
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        if cursor.fetchone() != (1,):
            raise ValueError('Database connection check failed')
    return {'status': 'ready', 'database_engine': engine,
            'operations': str(BACKEND / 'data/operations')}


def main():
    try:
        result = check()
    except (ValueError, ImportError) as exc:
        result = {'status': 'not_ready', 'reason': str(exc)}
    except Exception as exc:
        # Driver exception messages may include connection details.
        result = {'status': 'not_ready', 'error_type': type(exc).__name__,
                  'reason': 'Check database availability and backend/.env'}
    result['checked_at'] = datetime.now(timezone.utc).isoformat()
    try:
        atomic_json(BACKEND / 'data/operations/preflight-logs' / (uuid4().hex + '.json'), result)
    except OSError:
        result = {'status': 'not_ready', 'reason': 'Cannot write the local ETL diagnostic log'}
    print(json.dumps(result))
    return int(result['status'] != 'ready')


if __name__ == '__main__':
    raise SystemExit(main())
