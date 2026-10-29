"""Official DataJud aliases. Registry presence does not assert acquired coverage.

Source: https://datajud-wiki.cnj.jus.br/api-publica/endpoints/
"""
STATES = ('AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT',
          'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO')
COURT_NAMES = {'STJ': 'Superior Tribunal de Justiça', 'TST': 'Tribunal Superior do Trabalho',
               'TSE': 'Tribunal Superior Eleitoral', 'STM': 'Superior Tribunal Militar'}
COURT_NAMES.update({('TJDFT' if state == 'DF' else 'TJ' + state): 'Tribunal de Justiça — ' + state for state in STATES})
COURT_NAMES.update({f'TRF{i}': f'Tribunal Regional Federal da {i}ª Região' for i in range(1, 7)})
COURT_NAMES.update({f'TRT{i}': f'Tribunal Regional do Trabalho da {i}ª Região' for i in range(1, 25)})
COURT_NAMES.update({'TRE-' + state: 'Tribunal Regional Eleitoral — ' + state for state in STATES})
COURT_NAMES.update({'TJM' + state: 'Tribunal de Justiça Militar — ' + state for state in ('MG', 'RS', 'SP')})
COURTS = tuple(COURT_NAMES)
ACTIVE_COURTS = ('STJ', 'TJDFT', 'TJSP', 'TJMG', 'TJRJ', 'TJRS', 'TJPR', 'TRF1', 'TRF3', 'TST')
ENDPOINTS = {court: f'https://api-publica.datajud.cnj.jus.br/api_publica_{court.lower()}/_search' for court in COURTS}
# This alias is spelled tre-dft in the official endpoint directory.
ENDPOINTS['TRE-DF'] = 'https://api-publica.datajud.cnj.jus.br/api_publica_tre-dft/_search'
VALIDATED_OUTCOME_COURTS = ('TJDFT', 'STJ')


def matches_source(court, source):
    if not isinstance(source, str):
        return False
    value = source.upper().replace('-', '')
    if court == 'TRE-DF' and value == 'TREDFT':
        return True
    return value == court.replace('-', '')
