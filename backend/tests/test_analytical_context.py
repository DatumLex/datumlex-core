from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.http import QueryDict
from django.test import SimpleTestCase

from src.services import analytical_context


class AnalyticalContextUnitTests(SimpleTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            approved=True,
            must_change_password=False,
            support=False,
            courts=Mock(),
        )
        self.actor.courts.values_list.return_value = ["TJSP", "TJDFT", "TJAM"]
        clock = patch.object(analytical_context, "today", return_value=date(2026, 1, 15))
        clock.start()
        self.addCleanup(clock.stop)

    def test_defaults_use_only_active_assigned_courts_and_the_historical_period(self):
        context = analytical_context.resolve(self.actor, {})

        self.assertEqual(context["courts"], ["TJDFT", "TJSP"])
        self.assertEqual(context["start"], "2016-01-01")
        self.assertEqual(context["end"], "2026-01-15")

    def test_ineligible_accounts_are_rejected_before_reading_courts(self):
        for field, value in (
            ("is_authenticated", False),
            ("is_active", False),
            ("approved", False),
            ("must_change_password", True),
        ):
            with self.subTest(field=field), patch.object(self.actor, field, value):
                with self.assertRaisesMessage(PermissionError, "inactive_account"):
                    analytical_context.resolve(self.actor, {})

        self.actor.courts.values_list.assert_not_called()

    def test_active_court_outside_assignment_is_forbidden(self):
        with self.assertRaisesMessage(PermissionError, "court_forbidden"):
            analytical_context.resolve(self.actor, {"courts": ["STJ"]})

    def test_invalid_context_fields_are_rejected(self):
        for supplied, error in (
            ([], "context_object_required"),
            ({"extra": True}, "unknown_context_field"),
            ({"contract_version": "v2"}, "unsupported_context_version"),
            ({"courts": ["TJAM"]}, "invalid_courts"),
            ({"outcomes": ["other"]}, "invalid_outcomes"),
            ({"sources": "datajud"}, "invalid_sources"),
            ({"subject_codes": ["14"]}, "invalid_subject_codes"),
        ):
            with self.subTest(supplied=supplied), self.assertRaisesMessage(ValueError, error):
                analytical_context.resolve(self.actor, supplied)

    def test_date_must_use_the_extended_iso_format(self):
        with self.assertRaisesMessage(ValueError, "invalid_start"):
            analytical_context.resolve(self.actor, {"start": "20260101"})

    def test_query_uses_explicit_start_and_end_dates(self):
        query = QueryDict("start=2026-01-01&end=2026-01-10")
        context = analytical_context.from_query(self.actor, query)

        self.assertEqual(context["start"], "2026-01-01")
        self.assertEqual(context["end"], "2026-01-10")

    def test_invalid_date_ranges_are_rejected(self):
        for supplied in (
            {"start": "2009-12-31"},
            {"start": "2025-01-02", "end": "2025-01-01"},
            {"end": "2026-01-16"},
        ):
            with self.subTest(supplied=supplied), self.assertRaisesMessage(ValueError, "invalid_period"):
                analytical_context.resolve(self.actor, supplied)

    def test_query_canonicalizes_filters_and_preserves_empty_selection(self):
        query = QueryDict("court[]=TJSP&court[]=TJDFT&court[]=TJSP&outcome[]=&subject=14")
        context = analytical_context.from_query(self.actor, query)

        self.assertEqual(context["courts"], ["TJDFT", "TJSP"])
        self.assertEqual(context["outcomes"], [])
        self.assertEqual(context["subject_codes"], [14])

    def test_invalid_query_parameters_are_rejected(self):
        for query, error in (
            ("unknown=1", "unknown_query_field"),
            ("court[]=&court[]=TJSP", "mixed_empty_selection"),
            ("subject=14&subject=195", "repeated_scalar"),
            ("subject=%2B14", "invalid_subject"),
        ):
            with self.subTest(query=query), self.assertRaisesMessage(ValueError, error):
                analytical_context.from_query(self.actor, QueryDict(query))

    def test_equivalent_filters_have_the_same_context_identity(self):
        first = analytical_context.from_query(
            self.actor, QueryDict("court[]=TJSP&court[]=TJDFT&court[]=TJSP")
        )
        second = analytical_context.from_query(self.actor, QueryDict("court[]=TJDFT&court[]=TJSP"))
        different = analytical_context.from_query(self.actor, QueryDict("court[]=TJDFT"))

        self.assertEqual(analytical_context.identity(first), analytical_context.identity(second))
        self.assertNotEqual(analytical_context.identity(first), analytical_context.identity(different))
