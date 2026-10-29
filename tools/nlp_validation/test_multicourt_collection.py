import json
from pathlib import Path
import tempfile
import unittest
from datetime import date
from unittest.mock import patch
import collect_ementas
from collect_multicourt_publications import eligible, civil_text

class MulticourtCollectionTests(unittest.TestCase):
    def test_publication_requires_court_date_type_and_civil_theme(self):
        row={'tipoDocumento':'Acórdão','siglaTribunal':'TJSP','ativo':True,
             'data_disponibilizacao':'2026-10-20','texto':'Responsabilidade <b>civil</b> e dano moral. '*20}
        self.assertTrue(eligible(row,'TJSP',date(2026,10,1),date(2026,10,28)))
        self.assertFalse(eligible(row,'TJMG',date(2026,10,1),date(2026,10,28)))
        self.assertFalse(eligible({**row,'tipoDocumento':'Intimação'},'TJSP',date(2026,10,1),date(2026,10,28)))
        self.assertFalse(eligible({**row,'segredoJustica':True},'TJSP',date(2026,10,1),date(2026,10,28)))
        self.assertFalse(eligible(row,'TJSP',date(2025,10,1),date(2025,10,28)))
        self.assertFalse(civil_text('Acórdão eleitoral sobre registro de candidatura.'))
    def test_ementa_cursor_keeps_partially_consumed_resource(self):
        stj=[{'id':'S1','ementa':'Dano moral e responsabilidade civil. '*10,'dataDecisao':'20260101'},
             {'id':'S2','ementa':'Danos materiais e responsabilidade civil. '*10,'dataDecisao':'20260101'}]
        tst={'id':'T1','ementa':'Dano moral. '*20,'dtaJulgamento':'2026-01-01','orgao':{'sigla':'TST'},'tipo':{'codigoTipoJurisprudencia':'ACORDAO'}}
        def request(url,body=None):
            if 'package_search' in url:
                payload={'result':{'results':[{'name':'espelhos-de-acordaos-terceira-turma','resources':[{'url':'https://dadosabertos.web.stj.jus.br/20260101.json'}]}]}}
            elif url.endswith('/config.json'):payload={'base_url':'https://jurisprudencia-backend.tst.jus.br'}
            elif '/rest/' in url:payload={'registros':[{'registro':tst}]}
            else:payload=stj
            return json.dumps(payload).encode(),payload
        with tempfile.TemporaryDirectory() as temporary, patch.object(collect_ementas,'ROOT',Path(temporary)), patch.object(collect_ementas,'request',side_effect=request), patch.object(collect_ementas.time,'sleep'):
            result=collect_ementas.collect(limit=2)
            self.assertEqual(result['new'],2)
            cursor=json.loads((Path(temporary)/'jurisprudence-ementas/cursor.json').read_text())
            self.assertEqual(cursor['stj_resource_offset'],0)
            result=collect_ementas.collect(limit=2)
            self.assertEqual(result['new'],1)
            self.assertEqual(result['ementas_archived'],3)

if __name__=='__main__':unittest.main()
