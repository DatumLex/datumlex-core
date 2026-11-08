"""Explicit mapping between local court codes and the public Pangea catalog."""
from urllib.parse import urlparse
from src.db.court_catalog import ACTIVE_COURTS

PANGEA_ALIASES = {'TJDFT': 'TJDF', 'TRF1': 'TRF01', 'TRF3': 'TRF03'}

def canonical_court(value):
    code = str(value or '').strip().upper()
    return {alias: court for court, alias in PANGEA_ALIASES.items()}.get(code, code)

def selected_courts(values=None):
    values = ACTIVE_COURTS if values is None else values
    if isinstance(values, str):
        values = values.split(',')
    result = tuple(dict.fromkeys(canonical_court(value) for value in values if str(value).strip()))
    if not result or any(value not in ACTIVE_COURTS for value in result):
        raise ValueError('Selecione tribunais do escopo ativo: ' + ', '.join(ACTIVE_COURTS))
    return result

def source_organs(courts, catalog):
    available = {str(item['sigla']).upper() for item in catalog['orgaos']}
    organs = [PANGEA_ALIASES.get(court, court) for court in selected_courts(courts)]
    missing = [organ for organ in organs if organ not in available]
    if missing:
        raise ValueError('Tribunais indisponíveis no catálogo Pangea: ' + ', '.join(missing))
    return organs

def public_judicial_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or '').lower()
        return (parsed.scheme == 'https' and host.endswith('.jus.br')
                and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        return False
