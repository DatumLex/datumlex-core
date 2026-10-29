"""Read and reconcile the #111 queue against its actual local source artifacts."""

import json
import unicodedata
from pathlib import Path

from .contracts import bytes_hash
from src.db.court_catalog import matches_source


class SourceProblem(ValueError):
    pass


def read_source(row, root):
    root = Path(root).resolve()
    path = (root / row["artifact_path"]).resolve()
    if not path.is_relative_to(root):
        raise SourceProblem("artifact_outside_workspace")
    raw = path.read_bytes()
    if bytes_hash(raw) != row["artifact_sha256"]:
        raise SourceProblem("artifact_hash_mismatch")
    if row.get('source_format') == 'djen-public-json-v1':
        if row.get('content_kind') != 'publication_excerpt' or row.get('text_field') != 'texto':
            raise SourceProblem('content_kind_mismatch')
        records = [r for r in json.loads(raw)['items'] if str(r.get('id')) == str(row.get('record_id'))]
        if len(records) != 1:
            raise SourceProblem('ambiguous_document')
        record = records[0]
        kind = ''.join(c for c in unicodedata.normalize('NFD', str(record.get('tipoDocumento', '')))
                       if unicodedata.category(c) != 'Mn').casefold()
        if ('acordao' not in kind or not matches_source(row['court'], record.get('siglaTribunal'))
                or record.get('ativo') is False or record.get('data_cancelamento')):
            raise SourceProblem('publication_not_eligible')
        text = record.get('texto')
    elif row.get('source_format') in ('stj-espelhos-json-v1', 'tst-search-json-v1'):
        if row.get('content_kind') != 'ementa' or row.get('text_field') != 'ementa':
            raise SourceProblem('content_kind_mismatch')
        payload = json.loads(raw)
        if row['source_format'] == 'stj-espelhos-json-v1':
            if row['court'] != 'STJ' or not isinstance(payload, list):
                raise SourceProblem('source_court_mismatch')
            records = payload
        else:
            if row['court'] != 'TST':
                raise SourceProblem('source_court_mismatch')
            records = [item['registro'] for item in payload['registros']]
            records = [item for item in records if item.get('orgao', {}).get('sigla') == 'TST'
                       and item.get('tipo', {}).get('codigoTipoJurisprudencia') == 'ACORDAO']
        records = [item for item in records if str(item.get('id')) == str(row.get('record_id'))]
        if len(records) != 1:
            raise SourceProblem('ambiguous_document')
        text = records[0].get('ementa')
        if text == 'removido no backend':
            raise SourceProblem('missing_text')
    elif row["court"] == "STJ":
        if path.suffix.lower() != ".txt":
            raise SourceProblem("pdf_requires_traceable_extractor")
        text = raw.decode("utf-8", errors="strict")
    elif row["court"] == "TJDFT":
        if row.get("text_field") != "inteiroTeor":
            raise SourceProblem("unsupported_text_representation")
        uuid = row["document_id"].removeprefix("TJDFT:")
        records = [r for r in json.loads(raw)["registros"] if r["uuid"] == uuid]
        if len(records) != 1:
            raise SourceProblem("ambiguous_document")
        if records[0].get("segredoJustica") is not False:
            raise SourceProblem("source_eligibility_requires_review")
        text = records[0].get("inteiroTeor")
    else:
        raise SourceProblem("unsupported_court")
    if text is None or text == "":
        raise SourceProblem("missing_text")
    if not isinstance(text, str):
        raise SourceProblem("invalid_text_type")
    if not text.strip():
        raise SourceProblem("missing_text")
    if "\x00" in text:
        raise SourceProblem("invalid_nul_character")
    if bytes_hash(text.encode("utf-8")) != row["text_sha256"]:
        raise SourceProblem("text_hash_mismatch")
    if "source_text" in row and row["source_text"] != text:
        raise SourceProblem("queue_source_disagreement")
    return text
