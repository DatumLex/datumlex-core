"""Shared lexical civil liability topics; all matches require review."""
import re
import unicodedata

TOPICS = (
    ('dano-moral','Dano moral', ('dano moral','danos morais','dano extrapatrimonial','danos extrapatrimoniais')),
    ('dano-material','Dano material e reparação integral', ('dano material','danos materiais','lucros cessantes','reparacao integral','dano reparavel','dano patrimonial','danos patrimoniais')),
    ('saude','Responsabilidade em serviços de saúde', ('erro medico','responsabilidade medica','falha medica','servicos de saude','servico de saude')),
    ('transito','Acidentes de trânsito', ('acidente de transito','acidentes de transito','acidente automobilistico','atropelamento')),
    ('negativacao','Negativação indevida', ('negativacao indevida','inscricao indevida','cadastro de inadimplentes','cadastros de inadimplentes')),
    ('transporte-aereo','Transporte aéreo', ('transporte aereo','atraso de voo','cancelamento de voo','extravio de bagagem')),
    ('imovel','Atraso na entrega de imóvel', ('atraso na entrega','atraso de entrega','entrega do imovel','entrega de imovel')),
    ('imagem','Imagem, honra e privacidade', ('direito de imagem','direito a imagem','direito de privacidade','violacao da honra','uso indevido da imagem')),
    ('perda-chance','Perda de uma chance', ('perda de uma chance','perda da chance')),
    ('internet','Responsabilidade na internet', ('provedores de aplicacoes','provedor de aplicacoes','provedor de internet','provedores de internet','marco civil da internet','plataformas digitais')),
)

_DIACRITICS = re.compile(r'[\u0300-\u036f]')
_TERM_PATTERN = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(term) for term in
    sorted({term for _,_,terms in TOPICS for term in terms}, key=len, reverse=True)) + r')(?!\w)')

def folded(value):
    return ' '.join(_DIACRITICS.sub('', unicodedata.normalize('NFD', value.casefold())).split())

def classify(text):
    found={match.group() for match in _TERM_PATTERN.finditer(folded(text))}
    return {key:[term for term in terms if term in found]
            for key,_,terms in TOPICS if any(term in found for term in terms)}
