import unittest
import tempfile
import json
from pathlib import Path
import collect_doctrine
from unittest.mock import MagicMock, patch
from collect_doctrine import page_text
from datetime import date
from discover_ril import ArticleLinks, issue_urls, relevant_title

class DiscoveryTests(unittest.TestCase):
    def test_pdf_view_and_article_links_are_canonicalized_once(self):
        parser=ArticleLinks('https://www12.senado.leg.br/ril/edicoes/55/219')
        parser.feed('<a href="https://www12.senado.leg.br/ril/edicoes/55/219/ril_v55_n219_p209.pdf/view">Documento</a><a href="https://www12.senado.leg.br/ril/edicoes/55/219/ril_v55_n219_p209">Direito de imagem</a><a href="https://evil.test/ril/edicoes/55/219/ril_v55_n219_p209">Falso</a>')
        self.assertEqual(len(parser.links),1)
        self.assertTrue(next(iter(parser.links)).endswith('_p209'))
    def test_scope_uses_accent_insensitive_titles(self):
        self.assertTrue(relevant_title('Responsabilidade civil e indenização'))
        self.assertTrue(relevant_title('Direito à imagem'))
        self.assertFalse(relevant_title('Reforma eleitoral e processo legislativo'))
    @patch('collect_doctrine.PdfReader')
    def test_garbled_font_names_are_not_accepted_as_text(self, reader):
        pdf=MagicMock();pdf.is_encrypted=False
        page=MagicMock();page.extract_text.return_value='/u0049'*200
        pdf.pages=[page];reader.return_value=pdf
        with self.assertRaisesRegex(ValueError,'font mapping'):
            page_text(b'%PDF-fake')

    @patch('collect_doctrine.PdfReader')
    def test_readable_pdf_text_is_preserved(self, reader):
        pdf=MagicMock();pdf.is_encrypted=False
        page=MagicMock();page.extract_text.return_value='Responsabilidade civil. '*30
        pdf.pages=[page];reader.return_value=pdf
        pages,text=page_text(b'%PDF-fake')
        self.assertEqual(len(pages),1)
        self.assertIn('Responsabilidade civil',text)

    def test_raw_doctrine_is_preserved_before_pdf_text_processing(self):
        metadata=b'<meta name="citation_title" content="Responsabilidade civil de teste"><meta name="citation_publication_date" content="2024/03/15"><meta name="citation_pdf_url" content="https://www12.senado.leg.br/ril/edicoes/61/241/test.pdf">'
        raw=b'%PDF-synthetic-fixture'
        with tempfile.TemporaryDirectory() as temporary, patch.object(collect_doctrine,'ROOT',Path(temporary)), patch.object(collect_doctrine,'fetch',side_effect=[(metadata,'utf8'),(raw,None)]) as fetch, patch.object(collect_doctrine,'page_text') as parser, patch.object(collect_doctrine.time,'sleep'):
            result=collect_doctrine.collect(sources=[('Senado','https://www12.senado.leg.br/ril/edicoes/61/241/test')],extract_text=False)
            self.assertEqual(result['raw_pending'],1)
            self.assertEqual(result['doctrine_documents'],0)
            parser.assert_not_called()
            manifest=json.loads((Path(temporary)/'manifest.json').read_text(encoding='utf8'))
            entry=next(iter(manifest['pending'].values()))
            self.assertEqual((Path(temporary)/entry['pdf_path']).read_bytes(),raw)
            parser.return_value=([{'page':1,'text':'Texto sintetico'}],'Texto sintetico')
            converted=collect_doctrine.extract_entry(entry)
            self.assertEqual(converted['pages'],1)
            self.assertEqual(fetch.call_count,2)

    def test_dates_are_bounded_to_current_quarter(self):
        urls=list(issue_urls(date(2026,10,29)))
        self.assertEqual(len(urls),44)
        self.assertEqual(urls[0],'https://www12.senado.leg.br/ril/edicoes/53/209')
        self.assertEqual(len(list(issue_urls(date(2026,1,1)))),41)
        self.assertFalse(any('/64/' in url for url in urls))

if __name__=='__main__':unittest.main()
