from django.core.management.base import BaseCommand
from django.db import transaction

from src.db.models import LegalReference

SOURCE_URL = (
    "https://www.stj.jus.br/docs_internet/jurisprudencia/"
    "jurisprudenciaemteses/Jurisprudencia%20em%20Teses%20125%20-"
    "%20Responsabilidade%20Civil%20-%20Dano%20Moral.pdf"
)
SOURCE_NAME = "STJ — Jurisprudência em Teses, edição 125 (2019)"

THESIS_DATA = [
    {
        "identifier": "JTE-125-TESE-1",
        "title": "Dano moral: método bifásico de arbitramento",
        "thesis": (
            "A edição 125 da Jurisprudência em Teses resume que a fixação da "
            "indenização por dano moral deve considerar o método bifásico: "
            "circunstâncias do caso e interesse jurídico lesado, afastando "
            "arbitrariedade subjetiva e tarifação."
        ),
        "source_locator": "Edição 125, tese 1; julgados publicados até 26/04/2019",
        "related_decisions": [
            {"identifier": "AgInt no REsp 1533342/PR", "date": "2019-03-25"},
            {"identifier": "AgInt no AREsp 900932/MG", "date": "2019-02-25"},
            {"identifier": "REsp 1771866/DF", "date": "2019-02-12"},
            {"identifier": "AgInt no REsp 1719756/SP", "date": "2018-05-15"},
            {"identifier": "REsp 1669680/RS", "date": "2017-06-20"},
            {"identifier": "RCDESP no REsp 362532/PB", "date": "2012-08-07"},
        ],
    },
    {
        "identifier": "JTE-125-TESE-2",
        "title": "Dano moral coletivo como categoria autônoma",
        "thesis": (
            "A edição 125 resume que o dano moral coletivo, aferível in re ipsa, "
            "é categoria autônoma relacionada à violação injusta e intolerável "
            "de valores fundamentais da coletividade."
        ),
        "source_locator": "Edição 125, tese 2; julgados publicados até 26/04/2019",
        "related_decisions": [
            {"identifier": "REsp 1737428/RS", "date": "2019-03-12"},
            {"identifier": "REsp 1726270/BA", "date": "2018-11-27"},
            {"identifier": "AgInt no AREsp 100405/GO", "date": "2018-10-16"},
            {"identifier": "AgInt no AREsp 1312148/SP", "date": "2018-09-17"},
            {"identifier": "AgInt no AREsp 1113260/RJ", "date": "2018-08-16"},
            {"identifier": "REsp 1517973/PE", "date": "2017-11-16"},
        ],
    },
]


class Command(BaseCommand):
    help = "Load sourced STJ theses on civil liability as unapproved review candidates."

    @transaction.atomic
    def handle(self, *args, **options):
        for item in THESIS_DATA:
            LegalReference.objects.update_or_create(
                source_name=SOURCE_NAME,
                identifier=item["identifier"],
                defaults={
                    "reference_type": LegalReference.PRECEDENT,
                    "source_institution": "STJ",
                    "title": item["title"],
                    "thesis": item["thesis"],
                    "authority": "Secretaria de Jurisprudência do STJ",
                    "subject_code": None,
                    "source_url": SOURCE_URL,
                    "source_locator": item["source_locator"],
                    "published_at": "2019-05-17",
                    "approval_reference": "Fonte oficial cadastrada; aguarda aprovação do corpus pelo projeto",
                    "approved": False,
                    "related_decisions": item["related_decisions"],
                },
            )
        self.stdout.write(self.style.SUCCESS(f"Carregadas {len(THESIS_DATA)} teses rastreáveis do STJ como fontes pendentes de aprovação."))
