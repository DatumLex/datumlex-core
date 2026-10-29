import io
from datetime import date
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase, SimpleTestCase
from src.accounts.models import Court
from src.db.models import LegalCorpusItem, LegalCorpusTopicMatch, LegalReference
from src.services.corpus_catalog import classify, inventory, safe_url

class CorpusLexicalTests(SimpleTestCase):
    def test_accents_and_multi_topic_candidates(self):
        matches=classify('Responsabilidade no transporte aéreo. Danos morais e materiais; reparação integral.')
        self.assertIn('transporte-aereo',matches)
        self.assertIn('dano-moral',matches)
        self.assertIn('dano-material',matches)
        self.assertNotIn('dano-moral',classify('danomoralidade'))
    def test_link_sanitization(self):
        self.assertEqual(safe_url('javascript:alert(1)'), '')
        self.assertEqual(safe_url('https://secret@exemplo.test'), '')

class CorpusCatalogTests(TestCase):
    def setUp(self):
        self.actor=get_user_model().objects.create_user(username='corpus-test',approved=True,must_change_password=False)
        self.actor.courts.add(Court.objects.get_or_create(code='TJDFT',defaults={'name':'TJDFT'})[0])
        self.client.force_login(self.actor)
    def item(self,key,category='jurisprudence',court='TJDFT',topic='dano-moral',day=date(2020,1,1)):
        item=LegalCorpusItem.objects.create(origin_key=key,category=category,court=court,
            title=key,source_name='Teste',source_url='https://www.tjdft.jus.br/',
            content_kind='full_text',date=day,fingerprint=key)
        LegalCorpusTopicMatch.objects.create(item=item,topic=topic,matched_terms=['dano moral'])
        return item
    def query(self,extra=''):
        return inventory(QueryDict('court=TJDFT&start=2016-01-01&end=2026-01-01'+extra))
    def test_three_types_prioritized_and_doctrine_shared(self):
        self.item('decisao')
        self.item('precedente','precedent')
        self.item('artigo','doctrine',court='')
        self.item('outro',topic='transito')
        result=self.query()
        self.assertEqual(result['topics'][0]['id'],'dano-moral')
        self.assertTrue(result['topics'][0]['has_all_three'])
        result=self.query('&complete_only=true')
        self.assertEqual(result['counts'],{'jurisprudence':1,'precedent':1,'doctrine':1})
        self.assertEqual(result['items'][0]['review_status'],'pending')
    def test_dates_and_unknown_period_are_separate(self):
        self.item('known')
        self.item('unknown',day=None)
        self.item('old',day=date(2015,1,1))
        result=self.query()
        self.assertEqual(result['counts']['jurisprudence'],2)
        self.assertEqual(result['coverage']['undated'],1)
        result=self.query('&include_undated=false')
        self.assertEqual(result['counts']['jurisprudence'],1)
    def test_scope_does_not_leak_other_courts(self):
        self.item('mine')
        self.item('other',court='TJSP')
        self.assertEqual(self.query()['counts']['jurisprudence'],1)
        response=self.client.get('/api/corpus/?court=TJSP')
        self.assertEqual(response.status_code,403)
    def test_login_is_required(self):
        self.client.logout()
        self.assertEqual(self.client.get('/api/corpus/').status_code,401)
    def test_invalid_filters_rejected(self):
        for query in ('topic=invalid','category=bad','page=0','page_size=100','include_undated=maybe','start=2015-01-01'):
            self.assertEqual(self.client.get('/api/corpus/?'+query).status_code,400,query)
    def test_topic_overlap_does_not_double_count_document(self):
        item=self.item('unique')
        LegalCorpusTopicMatch.objects.create(item=item,topic='dano-material',matched_terms=['reparacao integral'])
        result=self.query()
        self.assertEqual(result['counts']['jurisprudence'],1)
        self.assertEqual(len(result['items'][0]['topics']),2)
    def test_pagination_and_title_search(self):
        for i in range(13):self.item(f'document-{i:02}')
        first=self.query('&page_size=12')
        second=self.query('&page_size=12&page=2')
        self.assertTrue(first['pagination']['has_next'])
        self.assertEqual(len(second['items']),1)
        self.assertEqual(self.query('&q=document-12')['counts']['jurisprudence'],1)
    def test_local_indexer_is_idempotent(self):
        reference=LegalReference.objects.create(reference_type='precedent',source_institution='TJSP',
            identifier='ref',title='Responsabilidade por dano moral',thesis='Dano moral',
            source_name='Pangea',source_url='https://pangeabnp.pdpj.jus.br/pesquisa',
            approval_reference='Pendente',source_metadata={},approved=False)
        for _ in range(2):call_command('refresh_legal_corpus',category='precedent',stdout=io.StringIO())
        self.assertEqual(LegalCorpusItem.objects.count(),1)
        self.assertEqual(LegalCorpusTopicMatch.objects.count(),1)
        item=LegalCorpusItem.objects.get()
        self.assertEqual(item.court,'TJSP')
        self.assertIsNone(item.date)
        self.assertEqual(item.review_status,'pending')
        reference.thesis='Acidente de transito';reference.title='Acidente de transito';reference.save()
        call_command('refresh_legal_corpus',category='precedent',stdout=io.StringIO())
        self.assertEqual(list(item.topic_matches.values_list('topic',flat=True)),['transito'])
