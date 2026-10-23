"""Task Scheduler entry point for automatic DataJud and Pangea/BNP syncs."""

import logging
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from src.db.subject_catalog import DEFAULT_DATAJUD_SUBJECT_CODES_CSV

PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"
LOG_DIR = BACKEND / "data"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("datumlex.datajud.scheduler")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    LOG_DIR / "datajud-scheduler.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)


def run_source(label: str, arguments: list[str]) -> int:
    command = [str(PYTHON), "manage.py", *arguments]
    logger.info("Starting %s sync", label)
    try:
        result = subprocess.run(
            command,
            cwd=BACKEND,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6 * 60 * 60,
            check=False,
        )
    except Exception:
        logger.exception("%s sync could not start", label)
        return 1
    if result.stdout:
        logger.info("%s: %s", label, result.stdout.rstrip())
    if result.stderr:
        logger.error("%s: %s", label, result.stderr.rstrip())
    logger.info("%s sync finished with exit code %s", label, result.returncode)
    return result.returncode


def main() -> int:
    datajud = [
        "sync_datajud",
        "--start",
        "2023-01-01",
        "--subjects",
        DEFAULT_DATAJUD_SUBJECT_CODES_CSV,
        "--page-size",
        "100",
        "--max-pages",
        "2",
    ]
    datajud_result = run_source("DataJud TJDFT/STJ", datajud)
    pangea_topics = [
        "responsabilidade civil",
        "direito do consumidor",
        "direito da saúde",
        "direito previdenciário",
        "direito administrativo",
        "direito tributário",
        "direito processual civil",
    ]
    pangea_results = [
        run_source(
            f"Pangea/BNP STJ · {topic}",
            ["sync_pangea", "--query", topic, "--page-size", "100", "--max-pages", "5"],
        )
        for topic in pangea_topics
    ]
    pangea_result = int(any(pangea_results))
    match_result = run_source("Reconciliação de citações STJ/TJDFT", ["match_stj_citations"])
    return 1 if datajud_result or pangea_result or match_result else 0


if __name__ == "__main__":
    sys.exit(main())
