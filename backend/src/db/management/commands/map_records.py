"""Persist deterministic mapping results and their full rule snapshot in JSON."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from src.services.deterministic_mapping import map_record, validate_rules


class Command(BaseCommand):
    help = "Map a JSON array of code/name/complement records using explicit evidence-backed rules."

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True, type=Path)
        parser.add_argument("--rules", required=True, type=Path)
        parser.add_argument("--output", required=True, type=Path)

    def handle(self, *args, **options):
        try:
            input_path = options["input"].resolve()
            rules = json.loads(options["rules"].read_text(encoding="utf-8"))
            records = json.loads(input_path.read_text(encoding="utf-8"))
            validate_rules(rules)
            if not isinstance(records, list):
                raise ValueError("Input must be a JSON array")
            results = [
                map_record(record, rules, {"file": str(input_path), "json_pointer": f"/{index}"})
                for index, record in enumerate(records)
            ]
            report = json.dumps({"rules": rules, "results": results}, ensure_ascii=False, indent=2)
            # Exclusive creation protects both source files and previous audit reports.
            with options["output"].open("x", encoding="utf-8") as output:
                output.write(report + "\n")
        except (OSError, ValueError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Mapped {len(results)} records to {options['output']}"))
