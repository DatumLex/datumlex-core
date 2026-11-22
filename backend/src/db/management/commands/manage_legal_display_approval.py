"""Auditable local CLI for display-only metadata approval of curated legal sources."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from src.services.legal_display_approval import (
    ALLOWED_CANDIDATES,
    ApprovalError,
    apply_display_approval,
    check_candidates,
    revoke_display_approval,
)


class Command(BaseCommand):
    help = "Check, simulate, apply, or revoke local display-only approval for allowlisted legal sources."
    requires_system_checks = []

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--check", action="store_true", help="Read-only verification of allowed candidates.")
        mode.add_argument("--dry-run", action="store_true", help="Simulate approval or revocation without persisting.")
        mode.add_argument("--apply", action="store_true", help="Apply display-only approval with human decision file.")
        mode.add_argument("--revoke", action="store_true", help="Revoke display-only approval using verified snapshot.")
        parser.add_argument(
            "--ids",
            nargs="+",
            default=[],
            help=f"Explicit source identifiers ({', '.join(sorted(ALLOWED_CANDIDATES))}).",
        )
        parser.add_argument("--decision-file", type=Path, help="Path to explicit human decision JSON.")
        parser.add_argument("--snapshot", type=Path, help="Path for/to pre-approval snapshot JSON (mode 0600).")
        parser.add_argument("--receipt", type=Path, help="Path for/to approval receipt JSON (mode 0600).")
        parser.add_argument(
            "--simulate-revoke",
            action="store_true",
            help="Used only with --dry-run to simulate revocation without writing.",
        )

    def handle(self, **options):
        try:
            if options["simulate_revoke"] and not options["dry_run"]:
                raise ApprovalError("--simulate-revoke só pode ser usado junto com --dry-run.")
            if options["check"]:
                result = check_candidates(options["ids"] or None)
            elif options["dry_run"] and options["simulate_revoke"]:
                if not options["snapshot"] or not options["receipt"]:
                    raise ApprovalError("Simulação de revogação exige --snapshot e --receipt.")
                result = revoke_display_approval(
                    options["ids"],
                    snapshot_path=options["snapshot"],
                    receipt_path=options["receipt"],
                    dry_run=True,
                )
            elif options["dry_run"]:
                result = apply_display_approval(
                    options["ids"],
                    decision_file=options["decision_file"],
                    dry_run=True,
                )
            elif options["apply"]:
                result = apply_display_approval(
                    options["ids"],
                    decision_file=options["decision_file"],
                    snapshot_path=options["snapshot"],
                    receipt_path=options["receipt"],
                    dry_run=False,
                )
            else:
                if not options["snapshot"] or not options["receipt"]:
                    raise ApprovalError("Revogação exige --snapshot e --receipt.")
                result = revoke_display_approval(
                    options["ids"],
                    snapshot_path=options["snapshot"],
                    receipt_path=options["receipt"],
                    dry_run=False,
                )
        except ApprovalError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
