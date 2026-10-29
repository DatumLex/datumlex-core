"""Immutable, partitioned computation cache. Originals are verified before reuse."""
import json
import sqlite3
from pathlib import Path
from .contracts import canonical, fingerprint

class ComputationCache:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.connections={}
    def connection(self,key):
        prefix=key[:2]
        if prefix not in self.connections:
            db=sqlite3.connect(self.root/(prefix+'.sqlite3'),timeout=30)
            db.execute('PRAGMA cache_size=-256')
            db.execute('CREATE TABLE IF NOT EXISTS results (key TEXT PRIMARY KEY,payload TEXT NOT NULL)');db.commit()
            self.connections[prefix]=db
        return self.connections[prefix]
    def get(self,key):
        row=self.connection(key).execute('SELECT payload FROM results WHERE key=?',(key,)).fetchone()
        if not row:return None
        result=json.loads(row[0]);expected=result.get('result_sha256')
        if fingerprint({k:v for k,v in result.items() if k!='result_sha256'})!=expected or result.get('computation_key')!=key:
            raise ValueError('computation_cache_integrity_failure')
        return result
    def put(self,key,result):
        if result['status'] not in ('completed','partial') or result['review']['status']!='pending':return
        db=self.connection(key)
        with db:db.execute('INSERT OR IGNORE INTO results VALUES (?,?)',(key,canonical(result)))
    def close(self):
        for db in self.connections.values():db.close()
