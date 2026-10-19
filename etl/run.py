"""Run the existing DataJud pipeline independently of the web server."""

import os
import sys
from pathlib import Path


def main():
    etl_dir = Path(__file__).resolve().parent
    backend_dir = etl_dir.parent / "backend"
    if not (backend_dir / "manage.py").is_file():
        raise SystemExit("Keep etl/ beside backend/ in the datumlex-core checkout.")

    try:
        from dotenv import load_dotenv
    except ImportError:
        raise SystemExit("Install ETL dependencies: python -m pip install -r requirements.txt") from None

    # Explicit process environment wins; etl/.env wins over backend/.env.
    load_dotenv(etl_dir / ".env", override=False)
    sys.path.insert(0, str(backend_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line([str(etl_dir / "run.py"), "extract_datajud", *sys.argv[1:]])


if __name__ == "__main__":
    main()
