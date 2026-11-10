"""Read-only Portuguese terminal summary of archived ETL state and volumes."""
import json
from collections import Counter, deque
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1] / 'data/operations'
STATES = {
    'running': 'Em andamento', 'completed': 'Concluído',
    'interrupted': 'Interrompido', 'partial_failure': 'Concluído com falhas',
    'partial': 'Parcial, com pendências', 'paused': 'Limite de lotes atingido',
    'failed': 'Falhou', 'failed_after_retries': 'Falhou após tentativas',
    'source_exhausted': 'Fonte sem novos resultados antes da meta',
}
STAGES = {
    'collect_doctrine': 'Buscando artigos do Senado',
    'collect_pangea': 'Buscando precedentes no Pangea',
    'collect_pangea_focused': 'Consultando temas especificos no Pangea',
    'collect_tjdft': 'Baixando acordaos completos do TJDFT',
    'collect_ementas': 'Buscando ementas do STJ e TST',
    'collect_djen': 'Buscando publicacoes no DJEN',
    'import_doctrine': 'Extraindo e importando doutrina',
    'import_pangea': 'Importando referencias do Pangea',
    'index_acquired': 'Atualizando o catalogo',
    'nlp': 'Analisando os textos com NLP',
    'import_nlp': 'Gravando os resultados do NLP no banco',
    'coverage': 'Gerando relatorio de cobertura',
    'collection_coverage': 'Conferindo cobertura da coleta',
}


def read_json(path, warnings):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        warnings.append(f'Leitura indisponivel: {path.name}')
        return None


def local_time(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime('%d/%m/%Y %H:%M:%S')
    except (ValueError, TypeError):
        return 'horario indisponivel'


def number(value):
    return f'{value:,}'.replace(',', '.') if value is not None else 'indisponivel'


def last_progress(log_directory, phase):
    """Read a bounded tail for the current stage, excluding old-stage progress."""
    latest = None
    paths = list(log_directory.glob(f'*-{phase}.*.log')) if phase else []
    for path in paths:
        try:
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 32768))
                lines = deque(stream.read().decode('utf8', errors='replace').splitlines(), maxlen=40)
            for line in reversed(lines):
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict) and any(key in value for key in ('processed', 'new_this_run', 'inspected', 'archived')):
                    candidate = (path.stat().st_mtime, value)
                    if latest is None or candidate[0] > latest[0]:
                        latest = candidate
                    break
        except OSError:
            continue
    return latest[1] if latest else {}


def snapshot(root):
    warnings = []
    runs = []
    for mode in ('collect', 'process', 'all'):
        state = read_json(root / f'etl-{mode}.json', warnings)
        if isinstance(state, dict) and state.get('started_at'):
            runs.append(state)
    runs.sort(key=lambda state: state['started_at'], reverse=True)
    active = [state for state in runs if state.get('status') == 'running']
    selected = active or runs[:1]
    tjdft = read_json(root / 'tjdft-documents/documents.json', warnings)
    ementas = read_json(root / 'jurisprudence-ementas/queue.json', warnings)
    djen = read_json(root / 'djen-documents/queue.json', warnings)
    doctrine = read_json(root / 'doctrine/manifest.json', warnings)
    pages = read_json(root / 'pangea-raw/all-pages.json', warnings)
    references = set()
    seen_paths = set()
    pangea_ok = pages is not None
    for entry in (pages or {}).get('pages', []):
        path = (root / 'pangea-raw' / entry.get('path', '')).resolve()
        if not path.is_relative_to((root / 'pangea-raw').resolve()):
            warnings.append('Caminho Pangea invalido no indice')
            pangea_ok = False
            continue
        if path in seen_paths:
            continue
        seen_paths.add(path)
        payload = read_json(path, warnings)
        if payload is None:
            pangea_ok = False
        for row in (payload or {}).get('resultados', []):
            if row.get('id') and row.get('orgao'):
                references.add((str(row['orgao']).upper(), row['id']))
    return {'runs': selected, 'warnings': warnings,
            'tjdft': len(tjdft) if tjdft is not None else None,
            'ementas': Counter(row.get('court') for row in ementas) if ementas is not None else None,
            'djen': len(djen) if djen is not None else None,
            'doctrine': len(doctrine.get('documents', {})) if doctrine is not None else None,
            'doctrine_pending': len(doctrine.get('pending', {})) if doctrine is not None else None,
            'doctrine_rejected': len(doctrine.get('rejected', {})) if doctrine is not None else None,
            'pangea': len(references) if pangea_ok else None}


def show_stj_pilot(root):
    pilots = []
    for path in (root / 'stj-pilot').glob('*/pilot.sqlite3'):
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)) as db:
                latest = db.execute('SELECT status, started_at, batches FROM stj_ingestion_run ORDER BY id DESC LIMIT 1').fetchone()
                if latest is None:
                    continue
                counts = dict(db.execute('SELECT text_status, COUNT(*) FROM stj_document GROUP BY text_status'))
                pilots.append((latest[1], latest[0], latest[2], counts, path.parent))
        except sqlite3.Error:
            continue
    if not pilots:
        return
    started, state, batches, counts, directory = max(pilots, key=lambda pilot: pilot[0])
    print('\nPILOTO STJ | BANCO SEPARADO')
    print(f"{STATES.get(state, state)} | Início: {local_time(started.replace(' ', 'T') + '+00:00')} | Lotes registrados: {number(batches)}")
    print(f"Textos disponíveis: {number(counts.get('available', 0))} | Textos ausentes: {number(counts.get('unavailable', 0))}")
    log = directory / 'live.log'
    if log.is_file():
        print('Log do piloto: ' + str(log))


def show(root=ROOT):
    data = snapshot(root)
    print('DATUMLEX | ACOMPANHAMENTO DA EXTRAÇÃO')
    print('Atualizado em ' + datetime.now().astimezone().strftime('%d/%m/%Y %H:%M:%S'))
    diagnostics = list((root / 'preflight-logs').glob('*.json'))
    if diagnostics:
        latest = max(diagnostics, key=lambda path: path.stat().st_mtime)
        setup = read_json(latest, data['warnings'])
        if setup:
            print('Última verificação do ambiente: ' + ('Pronto' if setup.get('status') == 'ready' else 'Requer atenção'))
            if setup.get('reason'):
                print('Motivo: ' + setup['reason'])
    for run in data['runs']:
        running = run.get('status') == 'running'
        indicator = '|/-\\'[int(datetime.now().timestamp()) % 4] if running else '*'
        print(f"\n{indicator} {STATES.get(run.get('status'), run.get('status', 'Sem estado'))}")
        modes = {'all': 'Ciclo completo', 'collect': 'Coleta', 'process': 'Processamento'}
        print(f"{modes.get(run.get('mode'), 'Execução')} | Início em {local_time(run.get('started_at'))}")
        if running:
            print('Etapa atual: ' + STAGES.get(run.get('phase'), run.get('phase') or 'Preparando'))
        else:
            print('Finalizada em ' + local_time(run.get('finished_at')))
        try:
            end = datetime.now(timezone.utc) if running else datetime.fromisoformat(run['finished_at'])
            seconds = max(0, int((end - datetime.fromisoformat(run['started_at'])).total_seconds()))
            print(f'Tempo de execução: {seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}')
        except (KeyError, ValueError, TypeError):
            pass
        if run.get('mode') != 'process' and 'tjdft' in run.get('sources', []) and run.get('target') and data['tjdft'] is not None:
            percent = min(100, data['tjdft'] / run['target'] * 100)
            print(f"Meta TJDFT desta execução: {number(data['tjdft'])} / {number(run['target'])} ({percent:.1f}%)")
        logs = root / 'etl-logs' / run['job_id']
        if running:
            progress = last_progress(logs, run.get('phase'))
            if 'processed' in progress:
                print(f"NLP: {number(progress['processed'])} / {number(progress.get('selected'))} textos; cache {number(progress.get('cached'))}")
            elif 'new_this_run' in progress:
                print('Novos no lote TJDFT: ' + number(progress['new_this_run']))
            elif 'inspected' in progress:
                print(f"Doutrina: {number(progress['inspected'])} candidatos inspecionados; {number(progress.get('new_candidates'))} selecionados")
            elif 'archived' in progress:
                print(f"Pangea: {number(progress['archived'])} linhas arquivadas na pagina {progress.get('page')}")
        for step in run.get('steps', []):
            if step.get('status') == 'failed':
                print('Falha: ' + STAGES.get(step['name'], step['name']))
                print('Log de erro: ' + step.get('stderr_log', 'consulte a pasta de logs'))
        if logs.is_dir():
            print('Logs desta execução: ' + str(logs))
    if not data['runs']:
        print('\nNenhuma execucao registrada nesta instalacao.')
    print('\nVOLUME ACUMULADO ARQUIVADO NESTA INSTALAÇÃO')
    print('TJDFT | acórdãos em inteiro teor: ' + number(data['tjdft']))
    print('Pangea | referências únicas por órgão e ID: ' + number(data['pangea']))
    counts = data['ementas']
    print('STJ e TST | ementas: ' + (f"{number(sum(counts.values()))} (STJ {number(counts['STJ'])}, TST {number(counts['TST'])})" if counts is not None else 'indisponivel'))
    print('DJEN | publicações: ' + number(data['djen']))
    print(f"Senado | textos extraídos: {number(data['doctrine'])}; pendentes {number(data['doctrine_pending'])}; extração alternativa {number(data['doctrine_rejected'])}")
    show_stj_pilot(root)
    for warning in data['warnings']:
        print('Aviso: ' + warning)


if __name__ == '__main__':
    show()
