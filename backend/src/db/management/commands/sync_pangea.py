"""Import public Pangea STJ precedents with source and coverage provenance."""

import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlencode

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.api.pangea_client import PangeaError, PangeaPublicSearchClient
from src.db.models import LegalReference, PangeaImportRun


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(value):
    if not isinstance(value, str):
        return ""
    parser = _TextOnly()
    parser.feed(value)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _source_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def _safe_paradigms(value, record_id):
    if not isinstance(value, list):
        return []
    citations = []
    for index, process in enumerate(value):
        if not isinstance(process, dict):
            continue
        number = process.get("numero")
        if not isinstance(number, str) or not number.strip():
            continue
        citation = {
            "identifier": number.strip()[:200],
            "locator": f"Pangea {record_id}.processosParadigma[{index}]",
        }
        link = process.get("link")
        if isinstance(link, str) and link.startswith("https://www.stj.jus.br/"):
            citation["url"] = link[:1000]
        class_name = process.get("classe")
        if isinstance(class_name, str):
            citation["class_code"] = class_name[:100]
        citations.append(citation)
    return citations


def _normalize(row, run, query):
    identifier = row.get("id")
    organ = str(row.get("orgao", "")).upper()
    kind = row.get("tipo")
    number = row.get("nr")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("Registro Pangea sem identificador, tipo ou número.")
    if not isinstance(kind, str) or not kind.strip() or isinstance(number, bool) or not isinstance(number, (int, str)):
        raise ValueError("Registro Pangea sem identificador, tipo ou número.")
    number = str(number).strip()
    if not number:
        raise ValueError("Registro Pangea sem identificador, tipo ou número.")
    if organ != "STJ":
        raise ValueError("A pesquisa Pangea retornou registro fora do escopo STJ.")
    if row.get("segredoJustica") is True:
        raise ValueError("Registro sinalizado como sigiloso.")

    question = _plain(row.get("questao"))
    thesis = _plain(row.get("tese"))
    text = thesis or (f"Questão (tese não informada): {question}" if question else "")
    if not text:
        text = f"Precedente {kind} nº {number}; tese não disponibilizada pela fonte."

    params = urlencode({"orgao": "stj", "tipo": kind, "nr": number})
    source_url = f"{settings.PANGEA_SEARCH_BASE_URL}/pesquisa?{params}"
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    metadata = {
        "orgao": organ,
        "tipo": kind,
        "nr": number,
        "situacao": str(row.get("situacao", ""))[:200],
        "ultimaAtualizacao": row.get("ultimaAtualizacao"),
        "questao": question,
        "query": query,
        "queries": [query],
        "processosParadigmaCount": len(_safe_paradigms(row.get("processosParadigma"), identifier)),
    }
    return {
        "reference_type": LegalReference.PRECEDENT,
        "source_institution": "STJ",
        "identifier": identifier[:200],
        "title": f"STJ — {kind} nº {number}"[:500],
        "thesis": text,
        "related_decisions": _safe_paradigms(row.get("processosParadigma"), identifier),
        "authority": str(kind)[:100],
        "subject_code": None,
        "source_name": "Pangea BNP — pesquisa pública STJ",
        "source_url": source_url[:1000],
        "source_locator": f"/api/v1/precedentes?q={query[:80]}&id={identifier}"[:300],
        # Pangea's ultimaAtualizacao is not a judgment or publication date.
        "published_at": None,
        "source_updated_at": _source_date(row.get("ultimaAtualizacao")),
        "source_metadata": metadata,
        "source_payload_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "last_import_run": run,
        "approval_reference": "Importado do Pangea público; aprovação jurídica pendente",
        "approved": False,
    }


class Command(BaseCommand):
    help = "Importa precedentes públicos do STJ no Pangea, preservando proveniência e cobertura."

    def add_arguments(self, parser):
        parser.add_argument("--query", default="responsabilidade civil")
        parser.add_argument("--page-size", type=int, default=100)
        parser.add_argument("--max-pages", type=int, default=5)

    def handle(self, *args, **options):
        query = options["query"].strip()
        size = options["page_size"]
        max_pages = options["max_pages"]
        if not query:
            raise CommandError("Informe um termo em --query.")
        if not 1 <= size <= 100 or max_pages < 1:
            raise CommandError("Use --page-size entre 1 e 100 e --max-pages maior que zero.")

        run = PangeaImportRun.objects.create(scope={
            "query": query,
            "organs": ["STJ"],
            "page_size": size,
            "max_pages": max_pages,
            "base_url": settings.PANGEA_SEARCH_BASE_URL,
            "endpoint": "/api/v1/precedentes",
        })
        client = PangeaPublicSearchClient()
        complete = False
        try:
            catalog = client.get_catalog()
            run.catalog_version = str(catalog.get("versao", ""))[:64]
            for page_index in range(max_pages):
                result = client.search_page(query, page_index, size)
                rows = result["resultados"]
                total = result["total"]
                run.source_total = total
                run.pages += 1
                run.fetched += len(rows)
                for row in rows:
                    try:
                        defaults = _normalize(row, run, query)
                    except ValueError:
                        run.rejected += 1
                        continue
                    with transaction.atomic():
                        existing = LegalReference.objects.filter(
                            source_name=defaults["source_name"],
                            identifier=defaults["identifier"],
                        ).first()
                        if existing is None:
                            LegalReference.objects.create(**defaults)
                            run.created += 1
                        else:
                            previous_queries = existing.source_metadata.get("queries", [])
                            if not isinstance(previous_queries, list):
                                previous_queries = []
                            defaults["source_metadata"]["queries"] = sorted(
                                {str(value) for value in previous_queries if value} | {query}
                            )
                            if existing.approved and existing.source_payload_hash != defaults["source_payload_hash"]:
                                defaults["approval_reference"] = (
                                    "Conteúdo da fonte atualizado; nova aprovação jurídica pendente"
                                )
                            changed = any(
                                getattr(existing, field) != value
                                for field, value in defaults.items()
                                if field != "last_import_run"
                            )
                            for field, value in defaults.items():
                                setattr(existing, field, value)
                            existing.save()
                            run.updated += int(changed)
                run.save()
                if not rows or (page_index + 1) * size >= total:
                    complete = True
                    break
            run.status = (
                PangeaImportRun.COMPLETED
                if complete and run.rejected == 0
                else PangeaImportRun.PARTIAL
            )
            run.finished_at = timezone.now()
            run.save()
        except (PangeaError, OSError, ValueError) as exc:
            run.status = PangeaImportRun.PARTIAL if run.pages else PangeaImportRun.FAILED
            run.error = str(exc)[:2000]
            run.finished_at = timezone.now()
            run.save()
            raise CommandError(f"Importação Pangea interrompida; execução {run.pk}: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(
            f"Pangea execução {run.pk}: {run.status}; {run.pages} páginas; "
            f"{run.fetched}/{run.source_total if run.source_total is not None else '?'} resultados; "
            f"{run.created} novos, {run.updated} atualizados, {run.rejected} rejeitados. "
            "As referências permanecem pendentes de aprovação jurídica."
        ))
