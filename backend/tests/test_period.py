from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from src.services import period


class PeriodUnitTests(SimpleTestCase):
    def test_today_uses_the_sao_paulo_date_across_utc_midnight(self):
        instant = datetime(2026, 1, 15, 1, 30, tzinfo=timezone.utc)

        with patch.object(period, "datetime") as clock:
            clock.now.side_effect = instant.astimezone
            local_date = period.today()

        self.assertEqual(local_date.isoformat(), "2026-01-14")
