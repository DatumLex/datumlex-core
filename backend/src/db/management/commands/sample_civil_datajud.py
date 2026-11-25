"""Report/reuse/fill a bounded, versioned DataJud sample without deleting warehouse data."""

import json
from collections import Counter
from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.api.datajud_client import DataJudClient, DataJudError
from src.db.civil_subjects import CATALOG, ROOT, SUBJECTS, branch_codes, primary_subject
from src.db.court_catalog import ACTIVE_COURTS
from src.db.models import ExtractionRun, FactProcess
from src.db.sampling_models import CivilSampleMember, CivilSamplingCohort
from src.etl.civil_sampling import Candidate, candidates_from_warehouse, choose
from src.etl.loader import load_record
from src.etl.transformer import InvalidRecord, normalize
from src.services.period import today


class Command(BaseCommand):
    help = "Report or materialize a stratified civil DataJud sample from public records."

    def add_arguments(self, parser):
        parser.add_argument("--courts", nargs="+", choices=ACTIVE_COURTS, default=list(ACTIVE_COURTS))
        parser.add_argument("--start-year", type=int, default=2010)
        parser.add_argument("--end", type=date.fromisoformat, default=today())
        parser.add_argument("--target", type=int, default=300)
        parser.add_argument("--subjects", nargs="+", type=int, choices=sorted(SUBJECTS), default=[ROOT])
        parser.add_argument("--cohort", default="civil-2010-sgt-2026-11")
        parser.add_argument("--seed", default="datumlex-civil-v1")
        parser.add_argument("--apply", action="store_true", help="Save sample membership in the local warehouse")
        parser.add_argument("--fetch", action="store_true", help="Request bounded complementary DataJud pages")
        parser.add_argument("--max-cells", type=int, default=1, help="Maximum tribunal/year cells to fetch per run")
        parser.add_argument("--pages-per-month", type=int, default=1)
        parser.add_argument("--page-size", type=int, default=50)
        parser.add_argument("--timeout", type=int, default=15)

    def handle(self, **options):
        courts = sorted(set(options["courts"]))
        start, end, target = options["start_year"], options["end"], options["target"]
        codes = sorted(set().union(*(branch_codes(code) for code in options["subjects"])))
        if not 2010 <= start <= end.year or end > today() or not 1 <= target <= 350:
            raise CommandError("Use anos de 2010 até hoje e meta de 1 a 350.")
        if not 1 <= options["max_cells"] or not 1 <= options["pages_per_month"] <= 10:
            raise CommandError("Use pelo menos uma célula e 1 a 10 páginas por mês.")
        if not 1 <= options["page_size"] <= 250 or not 1 <= options["timeout"] <= 120:
            raise CommandError("Página deve ter 1 a 250 documentos e timeout de 1 a 120 segundos.")
        if not 1 <= len(options["cohort"]) <= 64 or not all(
            character.isascii() and (character.isalnum() or character in "-_") for character in options["cohort"]
        ):
            raise CommandError("Use um nome de coorte com 1 a 64 letras, números, hífens ou underscores.")
        if options["fetch"] and (not options["apply"] or not settings.DATAJUD_API_KEY.strip()):
            raise CommandError("A coleta requer --apply e DATAJUD_API_KEY.")
        if options["apply"] and settings.DATABASES["default"].get("HOST", "") not in (
            "", "127.0.0.1", "localhost", "::1"
        ):
            raise CommandError("Materialize a amostra em um PostgreSQL local e revise antes de publicar.")
        definition = {
            "subjects": codes, "sgt_version": CATALOG["version"], "start_year": start,
            "target": target, "seed": options["seed"],
        }
        name = options["cohort"]
        cohort = CivilSamplingCohort.objects.filter(name=name).first()
        if cohort is None and options["apply"]:
            cohort, _ = CivilSamplingCohort.objects.get_or_create(name=name, defaults={"definition": definition})
        if cohort is not None and cohort.definition != definition:
            raise CommandError("Definição diferente para a mesma coorte. Escolha outro nome.")

        cells = [(court, year) for court in courts for year in range(start, end.year + 1)]
        remote_cells = 0
        for court, year in cells:
            lower, upper = date(year, 1, 1), min(date(year, 12, 31), end)
            rows = FactProcess.objects.filter(
                court=court, time__date__range=(lower, upper), subjects__code__in=codes,
                process_dimension__secrecy_level=0,
            )
            local = candidates_from_warehouse(rows, codes)
            fixed = self.members(cohort, court, year)
            prior = len(fixed)
            seed = f"{options['seed']}:{court}:{year}"
            local_additions = choose(local, max(0, target - prior), seed, fixed)
            remote, stats = [], None
            if options["fetch"] and prior + len(local_additions) < target and remote_cells < options["max_cells"]:
                remote_cells += 1
                remote, stats = self.scan(court, year, upper, codes, options)
            additions = local_additions + choose(
                remote, max(0, target - prior - len(local_additions)), seed, fixed + local_additions
            )
            if cohort is not None and options["apply"]:
                fixed, additions = self.save(cohort, court, year, upper, local, remote, stats, target, seed)
            selected = fixed + additions
            self.stdout.write(json.dumps({
                "court": court, "year": year, "existing_eligible": len({item.number for item in local}),
                "previous_members": len(fixed), "selected_from_warehouse": sum(item.fact_id is not None for item in additions),
                "new_from_datajud": sum(item.fact_id is None for item in additions), "target": target,
                "total": len(selected), "gap": max(0, target-len(selected)), "through": upper.isoformat(),
                "subjects": dict(sorted(Counter(item.subject for item in selected).items())),
                "months": dict(sorted(Counter(item.month for item in selected).items())),
                "remote_scan": stats, "applied": options["apply"], "coverage": "bounded_sample",
            }, sort_keys=True))

    @staticmethod
    def members(cohort, court, year):
        if cohort is None:
            return []
        return [
            Candidate(number, month, subject, source, fact_id=pk)
            for number, month, subject, source, pk in CivilSampleMember.objects.filter(
                cohort=cohort, court=court, year=year
            ).values_list("process__number_process", "filing_month", "subject_code", "fact__source_id", "fact_id")
        ]

    @staticmethod
    def scan(court, year, upper, codes, options):
        client = DataJudClient(settings.DATAJUD_API_KEY, court=court, timeout=options["timeout"], attempts=1)
        candidates = []
        stats = {"pages": 0, "fetched": 0, "rejected": 0, "errors": {}, "exhausted_months": []}
        eligible = set(codes)
        for month in range(1, upper.month + 1):
            first = date(year, month, 1)
            next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            scope = {
                "court": court, "start": first.isoformat(),
                "end_exclusive": min(next_month, upper + timedelta(days=1)).isoformat(),
                "subject_codes": codes, "page_size": options["page_size"], "track_total_hits": False,
            }
            cursor = None
            for _ in range(options["pages_per_month"]):
                try:
                    page = client.search(scope, cursor)
                except DataJudError as error:
                    stats["errors"][month] = str(error)
                    break
                hits = page["hits"]
                stats["pages"] += 1
                stats["fetched"] += len(hits)
                if not hits:
                    stats["exhausted_months"].append(month)
                    break
                cursor = hits[-1]["sort"]
                for hit in hits:
                    try:
                        record = normalize(hit, scope)
                    except InvalidRecord:
                        stats["rejected"] += 1
                        continue
                    candidates.append(Candidate(
                        record["number_process"], month, primary_subject(eligible.intersection(record["subjects"])),
                        record["source_id"], record=record,
                    ))
        return candidates, stats

    @transaction.atomic
    def save(self, cohort, court, year, upper, local, remote, stats, target, seed):
        CivilSamplingCohort.objects.select_for_update().get(pk=cohort.pk)
        fixed = self.members(cohort, court, year)
        local_picks = choose(local, max(0, target - len(fixed)), seed, fixed)
        remote_picks = choose(remote, max(0, target - len(fixed) - len(local_picks)), seed, fixed + local_picks)
        run = None
        if stats is not None:
            run = ExtractionRun.objects.create(
                scope={"origin": "civil_sampling", "cohort": cohort.name, "court": court,
                       "year": year, "through": upper.isoformat(), "remote_scan": stats},
                status="partial" if stats["errors"] else "sample",
                pages=stats["pages"], fetched=stats["fetched"], rejected=stats["rejected"],
                finished_at=timezone.now(),
            )
        for item in local_picks + remote_picks:
            if item.fact_id is None:
                action = load_record(item.record, run)
                setattr(run, action, getattr(run, action) + 1)
                fact = FactProcess.objects.get(source_id=item.source_id)
                # A newer warehouse revision can supersede a candidate from the remote page.
                if (fact.number_process != item.number or fact.time.year != year or fact.time.date > upper
                    or not fact.subjects.filter(code__in=cohort.definition["subjects"]).exists()):
                    continue
            else:
                fact = FactProcess.objects.get(pk=item.fact_id)
            CivilSampleMember.objects.create(
                cohort=cohort, fact=fact, process_id=fact.process_dimension_id, court=court, year=year,
                filing_month=item.month, subject_code=item.subject,
                origin="datajud" if item.fact_id is None else "warehouse",
            )
        if run is not None:
            run.save(update_fields=["created", "updated", "stale"])
        previous = {item.number for item in fixed}
        members = self.members(cohort, court, year)
        stored = {item.number for item in members} - previous
        return fixed, [item for item in local_picks + remote_picks if item.number in stored]
