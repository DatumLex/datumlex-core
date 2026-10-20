import hashlib
import json
from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from src.api.pangea_client import PangeaClient, PangeaError
from src.db.models import LegalReference


SOURCE_NAME = "Pangea/BNP — STJ Recurso Especial Repetitivo"
SOURCE_URL = "https://pangeabnp.pdpj.jus.br/"
RESOURCE = "recurso-repetitivo"


def _first_value(record, *keys):
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _text(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip() if value is not None else ""


def _court(record):
    value = _first_value(
        record,
        "siglaTribunal",
        "tribunal",
        "tribunalOrigem",
        "orgao",
        "siglaOrgao",
        "codigoTribunal",
    )
    if isinstance(value, dict):
        value = _first_value(value, "sigla", "codigo", "nome", "descricao")
    normalized = _text(value).upper()
    if "STJ" in normalized or "SUPERIOR TRIBUNAL DE JUSTIÇA" in normalized:
        return "STJ"
    if "TST" in normalized or "TRIBUNAL SUPERIOR DO TRABALHO" in normalized:
        return "TST"
    return ""


def _page_items(payload):
    if isinstance(payload, list):
        return payload, None, None
    for key in ("content", "items", "precedentes", "resultados", "data", "dados"):
        value = payload.get(key)
        if isinstance(value, list):
            total_pages = payload.get("totalPages", payload.get("total_pages"))
            total_elements = payload.get("totalElements", payload.get("total_elements"))
            return value, total_pages, total_elements
        if isinstance(value, dict):
            nested = _page_items(value)
            if nested[0] is not None:
                return nested
    if any(key in payload for key in ("id", "idPrecedente", "numeroTema", "numero")):
        return [payload], 1, 1
    return None, None, None


def _normalize(item):
    if not isinstance(item, dict):
        raise ValueError("record is not an object")
    identifier = _text(_first_value(
        item, "id", "idPrecedente", "idRecursoRepetitivo", "numeroTema", "numero", "tema"
    ))
    if not identifier:
        canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        identifier = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    title = _text(_first_value(item, "titulo", "title", "nome", "nomeTema", "tema"))
    if not title:
        title = f"Recurso especial repetitivo {identifier}"
    thesis = _text(_first_value(
        item,
        "tese",
        "teseFirmada",
        "questaoSubmetidaAJulgamento",
        "questaoJuridica",
        "descricaoTese",
        "descricao",
        "resumo",
    ))
    if not thesis:
        thesis = title
    status = _text(_first_value(item, "situacao", "status", "situacaoTema", "statusTema"))
    source_locator = f"API BNP/Pangea /v1/{RESOURCE}"
    if status:
        source_locator += f" · situação informada: {status}"
    processes = _first_value(
        item, "processosRepresentativos", "processos", "numerosProcessos", "recursosRepresentativos"
    ) or []
    if not isinstance(processes, list):
        processes = [processes]
    related = []
    for process in processes:
        if isinstance(process, dict):
            process_number = _first_value(process, "numero", "numeroProcesso", "numeroUnico", "processo")
            if process_number:
                related.append({"identifier": _text(process_number)})
        elif process:
            related.append({"identifier": _text(process)})
    published_at = None
    raw_date = _first_value(
        item, "dataJulgamento", "dataPublicacao", "dataAtualizacao", "dataDecisao", "data"
    )
    if raw_date:
        try:
            published_at = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            try:
                published_at = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).date()
            except ValueError:
                published_at = None
    return {
        "court": _court(item),
        "identifier": identifier[:200],
        "title": title[:500],
        "thesis": thesis,
        "authority": "Recurso Especial Repetitivo",
        "source_locator": source_locator[:300],
        "related_decisions": related,
        "published_at": published_at,
    }


class Command(BaseCommand):
    help = "Import STJ Recurso Especial Repetitivo precedents from the authenticated BNP/Pangea API."

    def add_arguments(self, parser):
        parser.add_argument("--page-size", type=int, default=100)
        parser.add_argument("--max-pages", type=int, default=5)
        parser.add_argument(
            "--if-configured",
            action="store_true",
            help="Skip cleanly when the scheduled job has no BNP client credentials yet.",
        )

    def handle(self, *args, **options):
        if not 1 <= options["page_size"] <= 100 or options["max_pages"] < 1:
            raise CommandError("Use page-size 1..100 and max-pages >= 1")
        try:
            client = PangeaClient()
        except PangeaError as exc:
            if options["if_configured"]:
                self.stdout.write(self.style.WARNING(f"Pangea ignorado: {exc}"))
                return
            raise CommandError(str(exc)) from None

        imported = created = updated = skipped_non_stj = 0
        for page_number in range(1, options["max_pages"] + 1):
            try:
                page = client.get_page(RESOURCE, page_number, options["page_size"])
            except PangeaError as exc:
                raise CommandError(str(exc)) from None
            items, total_pages, _ = _page_items(page)
            if items is None:
                raise CommandError("Formato de resposta BNP/Pangea não reconhecido; nenhum dado desta página foi importado.")
            if not items:
                break
            with transaction.atomic():
                for item in items:
                    try:
                        normalized = _normalize(item)
                    except (TypeError, ValueError):
                        continue
                    if normalized.pop("court") != "STJ":
                        skipped_non_stj += 1
                        continue
                    ref, was_created = LegalReference.objects.get_or_create(
                        source_name=SOURCE_NAME,
                        identifier=normalized["identifier"],
                        defaults={
                            "reference_type": LegalReference.PRECEDENT,
                            "source_institution": "STJ",
                            **normalized,
                            "subject_code": None,
                            "source_url": SOURCE_URL,
                            "approval_reference": "Importado do BNP/Pangea; aprovação jurídica pendente",
                            "approved": False,
                        },
                    )
                    if was_created:
                        created += 1
                    else:
                        changed = any(getattr(ref, field) != value for field, value in normalized.items())
                        for field, value in normalized.items():
                            setattr(ref, field, value)
                        if changed and ref.approved:
                            ref.approved = False
                            ref.approval_reference = "Fonte BNP/Pangea alterada; reaprovação jurídica necessária"
                        ref.save()
                        updated += 1
                    imported += 1
            self.stdout.write(
                f"Página {page_number}: {len(items)} itens recebidos; "
                f"{created} novos, {updated} atualizados."
            )
            if len(items) < options["page_size"] or (total_pages and page_number >= int(total_pages)):
                break

        self.stdout.write(self.style.SUCCESS(
            f"BNP/Pangea concluído: {imported} itens STJ importados, {created} novos, "
            f"{updated} atualizados, {skipped_non_stj} ignorados por não identificarem o STJ. "
            "As referências permanecem fora dos indicadores até a aprovação do corpus."
        ))
