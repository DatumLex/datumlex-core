"""Discovery by lexical topic, explicitly separate from validated legal analysis."""
import hashlib
import json
import re
import unicodedata
from datetime import date
from urllib.parse import urlparse
from django.db.models import Count, F, Max, Q
from src.db.models import LegalCorpusItem, LegalCorpusTopicMatch
from src.services.statistics_service import InvalidQuery, filtered_processes

VERSION = 'lexical_candidate_v1'
CATEGORIES = ('jurisprudence','precedent','doctrine')
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

def safe_url(value):
    if not isinstance(value,str):return ''
    try:
        parsed=urlparse(value)
        return value[:2000] if parsed.scheme in ('https','http') and parsed.hostname and not parsed.username and not parsed.password else ''
    except ValueError:return ''

def parse_date(value):
    try:return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:return None

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def inventory(params):
    allowed={'court','start','end','topic','category','page','page_size','q','include_undated','complete_only'}
    if set(params)-allowed or any(len(params.getlist(k))!=1 for k in params):
        raise InvalidQuery('Unsupported or repeated corpus filter')
    scope_params=params.copy()
    for key in list(scope_params):
        if key not in ('court','start','end'):scope_params.pop(key)
    _, scope=filtered_processes(scope_params)
    topic=params.get('topic','')
    category=params.get('category','jurisprudence')
    if topic and topic not in {key for key,_,_ in TOPICS}:raise InvalidQuery('Unknown responsibility-civil topic')
    if category not in CATEGORIES:raise InvalidQuery('Unknown corpus category')
    if params.get('include_undated','true') not in ('true','false') or params.get('complete_only','false') not in ('true','false'):
        raise InvalidQuery('Boolean filter must be true or false')
    try:
        page=int(params.get('page',1)); size=int(params.get('page_size',12))
        if page<1 or page>100000 or not 1<=size<=50:raise ValueError
    except ValueError:raise InvalidQuery('Invalid page or page size') from None
    query=params.get('q','').strip()
    if len(query)>120:raise InvalidQuery('Search title limited to 120 characters')
    base=LegalCorpusItem.objects.filter(Q(category='doctrine') | Q(court__in=scope['court'].split(',')))
    base=base.filter(topic_matches__isnull=False).distinct()
    in_period=Q(date__range=[scope['start'],scope['end']])
    if params.get('include_undated','true')=='true':in_period|=Q(date__isnull=True)
    base=base.filter(in_period)
    if query:base=base.filter(title__icontains=query)
    aggregated=LegalCorpusTopicMatch.objects.filter(item__in=base).values('topic','item__category').annotate(count=Count('item_id',distinct=True))
    counts_by_topic={key:dict.fromkeys(CATEGORIES,0) for key,_,_ in TOPICS}
    for row in aggregated:
        if row['topic'] in counts_by_topic:counts_by_topic[row['topic']][row['item__category']]=row['count']
    topics=[]
    for key,label,_ in TOPICS:
        counts=counts_by_topic[key]
        topics.append({'id':key,'label':label,'counts':counts,'has_all_three':all(counts.values()),'total':sum(counts.values())})
    topics.sort(key=lambda item:(-int(item['has_all_three']),-sum(v>0 for v in item['counts'].values()),-min(item['counts'].values()),-item['total'],item['id']))
    complete=params.get('complete_only','false')=='true'
    if complete:
        complete_keys=[item['id'] for item in topics if item['has_all_three']]
        base=base.filter(topic_matches__topic__in=complete_keys).distinct()
    if topic:base=base.filter(topic_matches__topic=topic).distinct()
    counts=dict.fromkeys(CATEGORIES,0)
    for row in base.values('category').annotate(count=Count('pk',distinct=True)):counts[row['category']]=row['count']
    undated=base.filter(date__isnull=True).count()
    items=base.filter(category=category).order_by(F('date').desc(nulls_last=True),'title','pk')
    total=counts[category]
    fields=('id','title','category','court','source_name','source_url','content_kind','date','date_kind','excerpt','authors','review_status','provenance__pending_nlp')
    page_rows=list(items.values(*fields)[(page-1)*size:page*size])
    matches={}
    for match in LegalCorpusTopicMatch.objects.filter(item_id__in=[row['id'] for row in page_rows]).values('item_id','topic','matched_terms'):
        matches.setdefault(match['item_id'],[]).append({'id':match['topic'],'terms':match['matched_terms']})
    for row in page_rows:
        row['processing_status']='awaiting_nlp' if row.pop('provenance__pending_nlp',False) else 'source_indexed'
        row['source_url']=safe_url(row['source_url'])
        row['topics']=matches.get(row['id'],[])
        row['period_confirmed']=row['date'] is not None
    return {'scope':scope,'topics':topics,'counts':counts,'items':page_rows,
            'pagination':{'page':page,'page_size':size,'total':total,'has_next':page*size<total},
            'classification':{'method':VERSION,'review_status':'pending','note':'Candidatos por termos no texto; nao comprovam vinculo juridico entre fontes.'},
            'coverage':{'undated':undated,'indexed_at':LegalCorpusItem.objects.aggregate(value=Max('indexed_at'))['value'],
                        'counting_unit':'unique_source_document','topics_overlap':True,
                        'doctrine_scope':'Bibliografia compartilhada, sem atribuicao a tribunal',
                        'topic_selection':'Dez temas iniciais; nao e ranking nacional de frequencia'}}
