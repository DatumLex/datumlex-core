"""Task Scheduler entry point for automatic DataJud and Pangea/BNP syncs."""

import logging
import json
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from src.db.subject_catalog import DEFAULT_DATAJUD_SUBJECT_CODES_CSV
from src.db.court_catalog import ACTIVE_COURTS as COURTS

PYTHON = Path(sys.executable)
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


def run_nlp_tools():
    tools = BACKEND.parent / 'tools/nlp_validation'
    # Selected-record budget: DataJud 200 + TJDFT 300 + DJEN 455 + ementas 45.
    collected = subprocess.run([str(PYTHON), str(tools / 'collect_tjdft_texts.py'), '--limit', '300'],
        cwd=BACKEND, capture_output=True, text=True, encoding='utf8', errors='replace', timeout=60 * 60)
    logger.info('TJDFT full texts: exit=%s\n%s', collected.returncode, collected.stdout.rstrip())
    failed = collected.returncode != 0
    for name, limit in [('collect_djen_acordaos.py', '455'), ('collect_ementas.py', '45')]:
        result = subprocess.run([str(PYTHON), str(tools / name), '--limit', limit], cwd=BACKEND,
            capture_output=True, text=True, encoding='utf8', errors='replace', timeout=60 * 60)
        logger.info('%s: exit=%s\n%s', name, result.returncode, result.stdout.rstrip())
        failed |= result.returncode != 0
    corpus = BACKEND / 'data/operations/stj-documents/texts'
    has_stj = corpus.exists() and any(corpus.glob('*.txt'))
    if not has_stj and not (BACKEND / 'data/operations/tjdft-documents/documents.json').exists():
        logger.warning('NLP pending: no archived full texts in this installation; metadata collection remains separate.')
        return 0
    for name, arguments in [('run_nlp_local.py', []), ('import_local_results.py', []),
                            ('nlp_validation.py', ['prepare']), ('report_coverage.py', [])]:
        result = subprocess.run([str(PYTHON), str(tools / name), *arguments], cwd=BACKEND,
                                capture_output=True, text=True, encoding='utf8', errors='replace',
                                timeout=60 * 60, check=False)
        logger.info('NLP %s: exit=%s\n%s', name, result.returncode, result.stdout.rstrip())
        if result.returncode:
            logger.error('NLP tool failed: %s', name)
            return result.returncode
    return int(failed)


def plan_courts(offset, page_budget=2):
    preferred = ('TJDFT', 'STJ', 'TJSP', 'TJMG', 'TJRJ', 'TJRS', 'TJPR', 'TRF1', 'TRF3', 'TST')
    sequence = tuple(dict.fromkeys((*preferred, *COURTS)))
    return [sequence[(offset + i) % len(sequence)] for i in range(page_budget)], (offset + page_budget) % len(sequence)


def run_court_batch(arguments):
    path = LOG_DIR / 'datajud-court-cursor.json'
    offset = json.loads(path.read_text())['offset'] if path.exists() else 0
    courts, next_offset = plan_courts(offset)
    results = [run_source(f'DataJud {court}', arguments + ['--court', court]) for court in courts]
    temporary = path.with_suffix('.part')
    temporary.write_text(json.dumps({'offset': next_offset, 'last_courts': courts}), encoding='utf8')
    temporary.replace(path)
    return int(any(results))


def main() -> int:
    # This scheduler is the local collection stage, never an implicit remote publisher.
    load_dotenv(BACKEND / '.env')
    import os
    database_url = os.environ.get('DATABASE_URL', '')
    if database_url and urlparse(database_url).hostname not in ('localhost', '127.0.0.1', '::1'):
        logger.error('Local automation requires a loopback database; remote publication is a separate step.')
        return 1
    datajud = [
        "sync_datajud",
        "--start",
        "2016-01-01",
        "--subjects",
        DEFAULT_DATAJUD_SUBJECT_CODES_CSV,
        "--page-size",
        "100",
        "--max-pages",
        "1",
    ]
    # One tribunal failure must not prevent collecting the other tribunal.
    datajud_result = run_court_batch(datajud)
    pangea_topics = ["responsabilidade civil"]
    pangea_results = [
        run_source(
            f"Pangea/BNP · {topic}",
            ["sync_pangea", "--query", topic, "--page-size", "100", "--max-pages", "5"],
        )
        for topic in pangea_topics
    ]
    pangea_result = int(any(pangea_results))
    match_result = run_source("Reconciliação de citações STJ/TJDFT", ["match_stj_citations"])
    nlp_result = run_nlp_tools()
    return 1 if datajud_result or pangea_result or match_result or nlp_result else 0


if __name__ == "__main__":
    sys.exit(main())
