"""Readiness and scheduler regression tests without source calls or task writes."""
import base64
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from scripts import check_etl_setup

PROJECT = Path(__file__).resolve().parents[2]
POWERSHELL = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


class EtlReadinessTests(SimpleTestCase):
    def test_missing_configuration_and_remote_targets_fail_before_connecting(self):
        with tempfile.TemporaryDirectory() as temporary:
            backend = Path(temporary)
            with patch.object(check_etl_setup, 'BACKEND', backend):
                with self.assertRaisesRegex(ValueError, 'backend/.env'):
                    check_etl_setup.check()
                (backend / '.env').touch()
                with patch.object(settings, 'DATABASES', {'default': {
                    'ENGINE': 'django.db.backends.postgresql', 'HOST': 'remote.invalid',
                }}), patch('django.db.connection.ensure_connection') as connect:
                    with self.assertRaisesRegex(ValueError, 'loopback'):
                        check_etl_setup.check()
                    connect.assert_not_called()

    def test_driver_errors_are_reported_without_connection_secrets(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary, patch.object(check_etl_setup, 'BACKEND', Path(temporary)):
            with patch.object(check_etl_setup, 'check', side_effect=RuntimeError('private-connection-secret')), redirect_stdout(output):
                self.assertEqual(check_etl_setup.main(), 1)
            report = json.loads(output.getvalue())
            self.assertEqual(report['status'], 'not_ready')
            self.assertNotIn('private-connection-secret', output.getvalue())
            record = next(Path(temporary).glob('data/operations/preflight-logs/*.json'))
            self.assertEqual(json.loads(record.read_bytes()), report)


@skipUnless(os.name == 'nt' and POWERSHELL.is_file(), 'Windows PowerShell required')
class SchedulePlanTests(SimpleTestCase):
    def run_powershell(self, script):
        command = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); " + script
        encoded = base64.b64encode(command.encode('utf-16le')).decode()
        return subprocess.run([str(POWERSHELL), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned', '-EncodedCommand', encoded],
                              capture_output=True, text=True, encoding='utf8', errors='replace', timeout=30)

    def copy_scripts(self, directory):
        for relative in ('scripts/install-schedule.ps1', 'backend/scripts/install_datajud_schedule.ps1'):
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT / relative, target)

    def test_different_clones_get_distinct_bounded_schedule_plans(self):
        plans = []
        with tempfile.TemporaryDirectory() as temporary:
            for name in ('clone one', 'clone two'):
                clone = Path(temporary) / name
                self.copy_scripts(clone)
                installer = str(clone / 'scripts/install-schedule.ps1').replace("'", "''")
                result = self.run_powershell(
                    "function Get-ScheduledTask { param($TaskName,$ErrorAction) }; "
                    "function Register-ScheduledTask { throw 'Unexpected task registration' }; "
                    f"$plan = & '{installer}' -At '03:25' -BatchSize 75 -Target 500 -Sources 'tjdft,pangea' -WhatIf; "
                    "$plan | ConvertTo-Json -Compress")
                self.assertEqual(result.returncode, 0, result.stderr)
                plan = json.loads(next(line for line in result.stdout.splitlines() if line.startswith('{')))
                self.assertEqual(plan['WorkingDirectory'], str(clone / 'backend'))
                self.assertIn('-Once', plan['Arguments'])
                self.assertIn('-BatchSize 75', plan['Arguments'])
                self.assertIn('-Sources tjdft,pangea', plan['Arguments'])
                self.assertIn('"' + str(clone / 'scripts/run-etl.ps1') + '"', plan['Arguments'])
                plans.append(plan)
        self.assertNotEqual(plans[0]['TaskName'], plans[1]['TaskName'])

    def test_a_custom_task_owned_by_another_clone_is_rejected(self):
        installer = str(PROJECT / 'scripts/install-schedule.ps1').replace("'", "''")
        result = self.run_powershell(
            "function Get-ScheduledTask { param($TaskName,$ErrorAction); "
            "[pscustomobject]@{Actions=@([pscustomobject]@{WorkingDirectory='C:/another-clone/backend'})} }; "
            f"& '{installer}' -TaskName 'ReservedTask' -WhatIf")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('another installation', result.stderr)
