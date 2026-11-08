import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/nlp_validation'))
from etl_runtime import Runtime,file_lock,archive_bytes

class ELTRuntimeTests(unittest.TestCase):
    def test_roles_can_run_separately_and_duplicate_role_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            backend=Path(temporary)
            with Runtime(backend,'collect'):
                with Runtime(backend,'process'):pass
                with self.assertRaises(OSError):
                    with Runtime(backend,'collect'):pass
    @patch('etl_runtime.owned_run',return_value=1)
    @patch('etl_runtime.shutil.disk_usage',return_value=SimpleNamespace(free=10**12))
    def test_failed_stage_is_durable_and_not_reported_as_completed(self,disk,run):
        with tempfile.TemporaryDirectory() as temporary:
            backend=Path(temporary)
            with Runtime(backend,'process') as runtime:
                self.assertEqual(runtime.run('import',['manage.py','import_pangea_raw']),1)
            state=json.loads((backend/'data/operations/etl-process.json').read_text())
            self.assertEqual(state['status'],'partial_failure')
            db=sqlite3.connect(backend/'data/operations/etl-state.sqlite3')
            self.assertEqual(db.execute('SELECT status FROM stages').fetchone()[0],'failed');db.close()
    def test_crashed_job_is_marked_interrupted_when_lock_is_available(self):
        with tempfile.TemporaryDirectory() as temporary:
            backend=Path(temporary)
            with Runtime(backend,'collect'):pass
            path=backend/'data/operations/etl-state.sqlite3';db=sqlite3.connect(path)
            db.execute("INSERT INTO jobs VALUES ('crashed','collect','running','past',NULL)");db.commit();db.close()
            with Runtime(backend,'collect'):pass
            db=sqlite3.connect(path)
            self.assertEqual(db.execute("SELECT status FROM jobs WHERE id='crashed'").fetchone()[0],'interrupted');db.close()

    def test_interrupted_artifact_is_preserved_and_repaired_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'artifact.json';path.write_bytes(b'partial')
            archive_bytes(path,b'{"complete":true}')
            self.assertEqual(path.read_bytes(),b'{"complete":true}')
            damaged=list(path.parent.glob('*.corrupt-*'))
            self.assertEqual(len(damaged),1);self.assertEqual(damaged[0].read_bytes(),b'partial')
            archive_bytes(path,b'{"complete":true}')
            self.assertEqual(len(list(path.parent.glob('*.corrupt-*'))),1)
