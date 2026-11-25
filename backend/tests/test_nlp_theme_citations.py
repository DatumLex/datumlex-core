from django.test import SimpleTestCase

from src.nlp.extraction import extract
from src.services.precedent_usage import extract as ementa_candidates


class ThemeCitationTests(SimpleTestCase):
    def test_explicit_themes_keep_original_offsets_and_unresolved_status(self):
        original = "A parte invoca o Tema repetitivo nº 1.083/STJ e o tema 999."
        extracted, _ = extract(original)
        authorities = [item for item in extracted if item.get("authority")]
        self.assertEqual(len(authorities), 1)
        authority = authorities[0]
        span = authority["segments"][0]
        self.assertEqual(original[span["start"]:span["end"]], "Tema repetitivo nº 1.083/STJ")
        self.assertEqual(authority["authority"]["resolution_status"], "unresolved")
        self.assertEqual(authority["context"]["adoption"]["value_status"], "unknown")

    def test_explicit_ementa_normalizes_identifier_without_promoting_party_mention(self):
        data = {"text_field": "ementa"}
        positive = ementa_candidates("Aplica-se o Tema repetitivo 1.083/STJ.", data)
        self.assertEqual([(item["authority_id"], item["status"]) for item in positive], [
            ("STJ:TEMA:1083", "applied"),
        ])
        party = ementa_candidates("O recorrente invoca o Tema repetitivo 1.083/STJ.", data)
        self.assertEqual(party[0]["status"], "ambiguous")
