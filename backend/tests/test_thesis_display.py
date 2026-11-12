import json
from django.test import RequestFactory, TestCase
from src.db.models import LegalReference
from src.nlp.thesis_display import describe_thesis
from src.routes.statistics import alignment

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
                related_decisions=[{'identifier':f'REsp {index}/DF'}])
        response = alignment(RequestFactory().get('/api/alignment/', {'court':'TJDFT','start':'2016-01-01','end':'2026-11-12'}))
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data['thesis_groups']), 308)
        self.assertEqual(len(data['source_theses']), 312)
        group = next(g for g in data['thesis_groups'] if g['title']=='Enunciado distinto 0')
        self.assertEqual(len(group['source_references']), 5)
        self.assertEqual(len(group['related_decisions']), 5)
        self.assertIn('nlp', group)
