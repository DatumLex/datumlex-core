"""Build verified NLP inputs from archived doctrine and Pangea responses."""
import json
from pathlib import Path
from urllib.parse import urlencode

from src.api.pangea_scope import canonical_court
from src.db.court_catalog import ACTIVE_COURTS
from .contracts import bytes_hash
from .adapters import read_source


def reference_queue(root, sources):
    root = Path(root).resolve()
    queue, excluded = {}, {}
    if 'pangea' in sources:
        index = root / 'pangea-raw/all-pages.json'
        if not index.exists():
            index = root / 'pangea-raw/manifest.json'
        receipts = json.loads(index.read_bytes()).get('pages', []) if index.exists() else []
        for page in receipts:
            artifact = (root / 'pangea-raw' / page['path']).resolve()
            if not artifact.is_relative_to((root / 'pangea-raw').resolve()):
                raise ValueError('Pangea artifact outside archive')
            raw = artifact.read_bytes()
            if bytes_hash(raw) != page['sha256']:
                raise ValueError('Pangea artifact hash mismatch')
            for record in json.loads(raw)['resultados']:
                court = canonical_court(record.get('orgao'))
                identifier = record.get('id')
                if (court not in ACTIVE_COURTS or not isinstance(identifier, str) or not identifier
                        or record.get('segredoJustica') is True):
                    continue
                key = 'PANGEA:' + court + ':' + identifier
                # A later revision can remove previously available text.
                queue.pop(key, None)
                field = 'tese' if isinstance(record.get('tese'), str) and record['tese'].strip() else 'questao'
                text = record.get(field)
                if not isinstance(text, str) or not text.strip():
                    excluded['precedent_without_text'] = excluded.get('precedent_without_text', 0) + 1
                    continue
                params = urlencode({'orgao': str(record['orgao']).lower(),
                                    'tipo': record.get('tipo', ''), 'nr': record.get('nr', '')})
                queue[key] = {
                    'document_id': key, 'court': court, 'category': 'precedent',
                    'source_format': 'pangea-public-json-v1', 'content_kind': 'precedent_reference',
                    'record_id': identifier, 'text_field': field,
                    'artifact_path': artifact.relative_to(root.resolve()).as_posix(),
                    'artifact_sha256': page['sha256'], 'text_sha256': bytes_hash(text.encode()),
                    'source_version': bytes_hash(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()),
                    'reference_payload_hash': bytes_hash(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                                                   separators=(',', ':')).encode()),
                    'source_url': 'https://pangeabnp.pdpj.jus.br/pesquisa?' + params,
                    'source_name': 'Pangea', 'publication_date': None,
                }
    if 'doctrine' in sources:
        path = root / 'doctrine/manifest.json'
        manifest = json.loads(path.read_bytes()) if path.exists() else {}
        for entry in manifest.get('documents', {}).values():
            if not entry.get('text_path') or not entry.get('text_sha256'):
                excluded['doctrine_without_verified_text'] = excluded.get('doctrine_without_verified_text', 0) + 1
                continue
            queue['DOCTRINE:' + entry['identifier']] = {
                'document_id': 'DOCTRINE:' + entry['identifier'], 'court': '',
                'category': 'doctrine', 'source_format': 'doctrine-text-v1',
                'content_kind': entry.get('content_kind', 'doctrine_article'),
                'artifact_path': 'doctrine/' + entry['text_path'],
                'artifact_sha256': entry['text_sha256'], 'text_sha256': entry['text_sha256'],
                'source_version': entry['pdf_sha256'], 'original_pdf_path': 'doctrine/' + entry['pdf_path'],
                'reference_payload_hash': entry['pdf_sha256'],
                'original_pdf_sha256': entry['pdf_sha256'],
                'source_url': entry['source_url'], 'source_name': entry['source_institution'],
                'publication_date': entry.get('published_at'), 'publication_year': entry.get('publication_year'),
                'text_field': 'utf8_txt',
            }
    for row in queue.values():
        read_source(row, root)
    return list(queue.values()), excluded
