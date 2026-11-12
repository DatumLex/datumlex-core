"""Engineering fixtures stay in the isolated test database, never the public corpus."""
from io import BytesIO

from django.test import TestCase
from pypdf import PdfReader

from src.db.models import NlpDocument, NlpTextVersion
from src.nlp.contracts import bytes_hash
from src.services.precedent_usage import extract, summarize
from tests.access_helpers import authorize_data


class PrecedentUsageTests(TestCase):
    scope = dict(court='TJDFT', subject=None, start='2024-01-01', end='2024-12-31')

    def version(self, text, key='TJDFT:engineering-only', **metadata):
        document, _ = NlpDocument.objects.get_or_create(source_key=key, defaults={'court': key.split(':')[0]})
        source = dict(document_id=key, court=document.court, text_field='inteiroTeor',
                      decision_date='2024-05-01', source_url='https://jurisdf.tjdft.jus.br/acordaos/test-only')
        source.update(metadata)
        return NlpTextVersion.objects.create(document=document, text=text,
            sha256=bytes_hash(text.encode()), fingerprint=bytes_hash((text + str(metadata)).encode()),
            source=source, representation={})

    def ementa(self, value):
        return 'EMENTA\n' + value + '\nACÓRDÃO\nRELATÓRIO\nO apelante alega aplicação da Súmula 7/STJ.'

    def test_direct_usage_and_exact_offsets(self):
        for sentence, expected in [
            ('Aplica-se a Súmula 54/STJ.', 'applied'),
            ('Aplica-se ao caso concreto a Súmula 54/STJ.', 'applied'),
            ('Incidência da Súmula 54 do STJ.', 'applied'),
            ('Súmula 54/STJ. APLICÁVEL.', 'applied'),
            ('Não se aplica a Súmula 54/STJ.', 'not_applied'),
            ('Não é aplicável a Súmula 54/STJ.', 'not_applied'),
            ('Inaplicabilidade da Súmula 54/STJ.', 'not_applied'),
            ('Tema 970 do STJ. Inaplicável.', 'not_applied'),
            ('Conforme a Súmula 54/STJ.', 'mentioned'),
        ]:
            with self.subTest(sentence=sentence):
                text = self.ementa(sentence)
                items = extract(text, {'text_field': 'inteiroTeor'})
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]['status'], expected)
                item = items[0]
                self.assertEqual(text[item['start']:item['end']], item['excerpt'])
                self.assertEqual(text[item['citation_start']:item['citation_end']], item['authority_literal'])

    def test_quotes_party_voice_negation_multiple_and_missing_sections_abstain(self):
        for sentence in [
            'O apelante requer aplicação da Súmula 54/STJ.',
            '“Aplica-se a Súmula 54/STJ.”',
            'Não há aplicação da Súmula 54/STJ.',
            'Afasta-se a aplicação da Súmula 54/STJ.',
            'Impossibilidade de aplicação da Súmula 54/STJ.',
            'Não há falar em inaplicabilidade da Súmula 54/STJ.',
            'Aplica-se a Súmula 54/STJ, mas não a Súmula 362/STJ.',
        ]:
            with self.subTest(sentence=sentence):
                self.assertTrue(all(item['status'] == 'ambiguous'
                    for item in extract(self.ementa(sentence), {'text_field': 'inteiroTeor'})))
        self.assertEqual(extract(self.ementa('Súmula 54/STJ. Incidência do CDC.'), {})[0]['status'], 'mentioned')
        self.assertIsNone(extract('RELATÓRIO\nAplica-se a Súmula 54/STJ.', {}))
        self.assertIsNone(extract('EMENTA\nAplica-se a Súmula 54/STJ.', {}))
        self.assertEqual(extract(self.ementa('Aplica-se o Tema 970.'), {}), [])

    def test_deduplicate_conflicts_and_rate_excludes_citations(self):
        self.version(self.ementa('Aplica-se a Súmula 54/STJ.\n\nAplica-se a Súmula 54/STJ.'))
        self.version(self.ementa('Inaplicabilidade da Súmula 362/STJ.'), key='TJDFT:negative')
        self.version(self.ementa('Súmula 7/STJ.'), key='TJDFT:mention')
        result = summarize(self.scope)
        self.assertEqual(result['counts'], dict(applied=1, not_applied=1, mentioned=1, ambiguous=0))
        self.assertEqual(result['application_rate'], 0.5)
        self.assertEqual(result['denominator'], 2)
        self.version(self.ementa('Aplica-se a Súmula 54/STJ.\n\nNão se aplica a Súmula 54/STJ.'))
        result = summarize(self.scope)
        self.assertEqual(result['counts']['ambiguous'], 1)
        self.assertEqual(result['denominator'], 1)

    def test_filters_source_integrity_latest_version_and_no_manual_review(self):
        self.version(self.ementa('Aplica-se a Súmula 54/STJ.'))
        self.version(self.ementa('Aplica-se a Súmula 54/STJ.'), key='STJ:other')
        self.version(self.ementa('Aplica-se a Súmula 54/STJ.'), key='TJDFT:undated', decision_date=None)
        self.version(self.ementa('Aplica-se a Súmula 54/STJ.'), key='TJDFT:outside', decision_date='2020-01-01')
        self.version(self.ementa('Aplica-se a Súmula 54/STJ.'), key='TJDFT:reference', category='precedent')
        self.version(self.ementa('Aplica-se a Súmula 54/STJ.'), key='TJDFT:unsafe', source_url='https://example.invalid/source')
        result = summarize(self.scope)
        self.assertEqual(result['counts']['applied'], 1)
        self.assertEqual(result['coverage']['undated'], 1)
        self.assertEqual(result['coverage']['outside_period'], 1)
        self.assertEqual(summarize(self.scope | {'subject': 10433})['denominator'], 0)
        # A new version replaces the old text, rather than adding a second vote.
        self.version(self.ementa('Súmula 54/STJ.'))
        self.assertEqual(summarize(self.scope)['counts']['applied'], 0)


    def test_tampered_text_and_fixture_sources_are_excluded(self):
        version = self.version(self.ementa('Aplica-se a Súmula 54/STJ.'))
        NlpTextVersion.objects.create(document=version.document, text=version.text + ' altered',
            sha256=version.sha256, fingerprint='0' * 64, source=version.source, representation={})
        result = summarize(self.scope)
        self.assertEqual(result['denominator'], 0)
        self.assertEqual(result['coverage']['integrity_failed'], 1)
        self.version(self.ementa('Aplica-se a Súmula 54/STJ.'), key='TJDFT:fixture', data_mode='fixture')
        self.assertEqual(summarize(self.scope)['denominator'], 0)

    def test_endpoint_permissions_pagination_and_pdf_use_same_real_calculation(self):
        authorize_data(self.client)
        self.version(self.ementa('Aplica-se a Súmula 54/STJ.'))
        query = '?court=TJDFT&start=2024-01-01&end=2024-12-31'
        result = self.client.get('/api/precedent-usage/' + query)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['application_rate'], 1)
        self.assertEqual(self.client.get('/api/precedent-usage/?court=STJ').status_code, 403)
        self.assertEqual(self.client.get('/api/precedent-usage/' + query + '&page_size=0').status_code, 400)
        self.assertEqual(self.client.get('/api/precedent-usage/' + query + '&page=2').json()['items'], [])
        stats = self.client.get('/api/statistics/' + query).json()['precedent_usage']
        self.assertEqual(stats['counts'], result.json()['counts'])
        pdf = self.client.get('/api/report.pdf/' + query)
        self.assertEqual(pdf.status_code, 200)
        text = ' '.join(' '.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages).split())
        self.assertIn('100,0%', text)
        self.assertIn('Aplicação de precedentes', text)
        self.assertIn('Aplica-se a Súmula 54/STJ.', text)
        self.assertNotIn('Aderência revisada', text)
        self.client.logout()
        self.assertEqual(self.client.get('/api/precedent-usage/' + query).status_code, 401)
