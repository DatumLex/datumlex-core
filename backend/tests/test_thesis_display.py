from django.contrib.auth import get_user_model
from django.test import TestCase
from src.accounts.models import Court
from src.db.models import LegalReference
from src.nlp.thesis_display import describe_thesis
from tests.access_helpers import authorize_data

class ThesisDisplayTests(TestCase):
    def test_extractive_summary_preserves_negation_and_conditions(self):
        text = 'Não há dano moral sem prova das circunstâncias concretas. A análise exige revisão.'
        result = describe_thesis(text)
        self.assertEqual(result['summary'], 'Não há dano moral sem prova das circunstâncias concretas.')
        self.assertIn('dano moral', result['nlp']['matched_terms'])
        self.assertLessEqual(len(result['label']), 65)

    def test_alignment_returns_every_group_and_source(self):
        for index in range(312):
            LegalReference.objects.create(reference_type='precedent',source_institution='STJ',
                identifier=f'test-{index}',title=f'Tese {index}',
                thesis=f'Enunciado distinto {index}' if index < 308 else 'Enunciado distinto 0',
                source_name='Teste',source_url='https://www.stj.jus.br/',
                approved=True,source_metadata={'permissions':{'display':'allowed'}},
                related_decisions=[{'identifier':f'REsp {index}/DF'}])
        LegalReference.objects.create(reference_type='precedent',source_institution='STJ',
            identifier='test-pending',title='Tese pendente',thesis='Enunciado pendente',
            source_name='Teste',source_url='https://www.stj.jus.br/',approved=False,source_metadata={})
        params = {'court':'TJDFT','start':'2016-01-01','end':'2026-11-12'}
        # Real HTTP requests must enforce authentication (401) and court authorization (403) without 500s.
        self.assertEqual(self.client.get('/api/alignment/', params).status_code, 401)
        other = get_user_model().objects.create_user(username='thesis-stj-only',approved=True,must_change_password=False)
        other.courts.add(Court.objects.get_or_create(code='STJ',defaults={'name':'STJ'})[0])
        self.client.force_login(other)
        self.assertEqual(self.client.get('/api/alignment/', params).status_code, 403)

        authorize_data(self.client)
        response = self.client.get('/api/alignment/', params)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data['thesis_groups']), 308)
        self.assertEqual(len(data['source_theses']), 312)
        self.assertNotIn('test-pending', {item['identifier'] for item in data['source_theses']})
        group = next(g for g in data['thesis_groups'] if g['title']=='Enunciado distinto 0')
        self.assertEqual(len(group['source_references']), 5)
        self.assertEqual(len(group['related_decisions']), 5)
        self.assertIn('nlp', group)
