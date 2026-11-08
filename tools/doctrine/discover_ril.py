"""Bounded discovery of scholarly articles from official Senate RIL issue indexes."""
import json
import hashlib
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from collect_doctrine import ROOT, fetch, CitationMetadata, parse_date
from src.services.period import today

ARTICLE = re.compile(r'^https://www12\.senado\.leg\.br/ril/edicoes/\d+/\d+/ril_v\d+_n\d+_p\d+(?:\.pdf(?:/view)?)?$')
TERMS=('responsabilidade civil','dano moral','danos morais','dano material','danos materiais',
       'indenizacao','reparacao integral','perda de uma chance','direito a imagem',
       'direito de imagem','transporte aereo','erro medico','responsabilidade medica',
       'negativacao indevida','provedores de aplicacoes','provedor de aplicacoes')

def relevant_title(title):
    normalized=''.join(c for c in unicodedata.normalize('NFD',title.casefold()) if not unicodedata.combining(c))
    return any(term in normalized for term in TERMS)

class ArticleLinks(HTMLParser):
    def __init__(self,base):
        super().__init__();self.base=base;self.href=None;self.parts=[];self.links={}
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.href=dict(attrs).get('href');self.parts=[]
    def handle_data(self,data):
        if self.href:self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.href:
            url=urljoin(self.base,self.href)
            if ARTICLE.fullmatch(url):
                canonical=re.sub(r'\.pdf(?:/view)?$','',url)
                title=' '.join(self.parts).strip()
                if canonical not in self.links or len(title)>len(self.links[canonical]):self.links[canonical]=title
            self.href=None

def issue_urls(day=None):
    day=day or today()
    # Interleave years so bounded runs do not favor a single year.
    for quarter in range(4):
        for year in range(2016,day.year+1):
            if year==day.year and quarter*3+1>day.month:continue
            yield f'https://www12.senado.leg.br/ril/edicoes/{year-1963}/{209+(year-2016)*4+quarter}'

def save(path,value):
    from etl_runtime import atomic_json
    atomic_json(path,value)


def inspect_article(pair):
    url,anchor=pair
    if anchor and not re.fullmatch(r'ril_v\d+_n\d+_p\d+\.pdf',anchor) and not relevant_title(anchor):
        return url,{'state':'title_outside_scope','title':anchor}
    try:
        raw,charset=fetch(url,2_000_000)
        parser=CitationMetadata();parser.feed(raw.decode(charset))
        title=parser.values.get('citation_title',[''])[0]
        publication=parse_date(parser.values.get('citation_publication_date',[''])[0])
        valid=bool(title and relevant_title(title) and publication and date(2016,1,1)<=publication<=today()
                   and parser.values.get('citation_pdf_url'))
        return url,{'state':'selected' if valid else 'metadata_outside_scope','title':title,
                    'published_at':publication.isoformat() if publication else None}
    except Exception as exc:
        return url,{'state':'metadata_unavailable','error_type':type(exc).__name__,'http_status':getattr(exc,'code',None)}

def discover(limit=50,max_issues=44,max_candidates=600):
    if not 1<=limit<=100 or not 1<=max_issues<=44 or not 1<=max_candidates<=600:
        raise ValueError('Discovery exceeds bounded request budget')
    ROOT.mkdir(parents=True,exist_ok=True)
    state_path=ROOT/'discovery.json'
    state=json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {'issues':{},'articles':{}}
    manifest_path=ROOT/'manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf8')) if manifest_path.exists() else {'documents':{}}
    known=set();repair_urls=[]
    for entry in manifest['documents'].values():
        try:
            pdf=(ROOT/entry['pdf_path']).resolve();text=(ROOT/entry['text_path']).resolve()
            valid=pdf.is_relative_to(ROOT.resolve()) and text.is_relative_to(ROOT.resolve())
            valid=valid and hashlib.sha256(pdf.read_bytes()).hexdigest()==entry['pdf_sha256']
            valid=valid and hashlib.sha256(text.read_text(encoding='utf8').encode('utf8')).hexdigest()==entry['text_sha256']
        except (OSError,ValueError,KeyError):valid=False
        if valid:known.add(entry['source_url'])
        else:repair_urls.append(entry['source_url'])
    for entry in list(manifest.get('pending',{}).values())+list(manifest.get('rejected',{}).values()):
        try:
            path=(ROOT/entry['pdf_path']).resolve()
            valid=path.is_relative_to(ROOT.resolve()) and hashlib.sha256(path.read_bytes()).hexdigest()==entry['pdf_sha256']
        except (OSError,ValueError,KeyError):valid=False
        if valid:known.add(entry['source_url'])
        else:repair_urls.append(entry['source_url'])
    links={}
    for url in list(issue_urls())[:max_issues]:
        cached=state['issues'].get(url)
        current_volume=f'/edicoes/{today().year-1963}/' in url
        if cached and cached.get('state')=='read' and (not current_volume or cached.get('checked_date')==today().isoformat()):
            links.update(cached['links']);continue
        try:
            raw,charset=fetch(url,2_000_000);parser=ArticleLinks(url);parser.feed(raw.decode(charset))
            links.update(parser.links)
            state['issues'][url]={'state':'read','links':parser.links,'checked_date':today().isoformat()}
        except Exception as exc:
            state['issues'][url]={'state':'unavailable','error_type':type(exc).__name__,'http_status':getattr(exc,'code',None)}
        save(state_path,state)
        print(json.dumps({'phase':'doctrine_discovery','issues_read':sum(v['state']=='read' for v in state['issues'].values()),'article_links':len(links)}),flush=True)
        time.sleep(.2)
    selected=list(dict.fromkeys(repair_urls+[url for url,entry in state['articles'].items() if entry['state']=='selected' and url not in known]))
    pending=[(url,title) for url,title in links.items() if url not in known and
             (url not in state['articles'] or state['articles'][url]['state']=='metadata_unavailable' and state['articles'][url].get('checked_date')!=today().isoformat())]
    for offset in range(0,min(len(pending),max_candidates),20):
        if len(selected)>=limit:break
        with ThreadPoolExecutor(max_workers=3) as pool:
            for url,entry in pool.map(inspect_article,pending[offset:min(offset+20,max_candidates)]):
                state['articles'][url]={**entry,'checked_date':today().isoformat()}
                if entry['state']=='selected' and url not in selected:selected.append(url)
        save(state_path,state)
        print(json.dumps({'phase':'doctrine_metadata','inspected':len(state['articles']),'new_candidates':len(selected)}),flush=True)
        time.sleep(.2)
    return selected[:limit]
