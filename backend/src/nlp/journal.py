"""Atomic, append-only attempts and immutable completed results, single worker."""

import json
import sqlite3

from .contracts import canonical


class Journal:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, job_key TEXT, "
                        "status TEXT, payload TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        self.db.execute("CREATE TABLE IF NOT EXISTS completed (job_key TEXT PRIMARY KEY, payload TEXT)")
        self.db.commit()

    def get(self, key):
        row = self.db.execute("SELECT payload FROM completed WHERE job_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def record(self, key, result, reusable):
        payload = canonical(result)
        with self.db:
            self.db.execute("INSERT INTO attempts(job_key,status,payload) VALUES (?,?,?)",
                            (key, result["status"], payload))
            if reusable:
                previous = self.db.execute("SELECT payload FROM completed WHERE job_key=?", (key,)).fetchone()
                if previous and previous[0] != payload:
                    raise ValueError("immutable_result_conflict")
                self.db.execute("INSERT OR IGNORE INTO completed VALUES (?,?)", (key, payload))

    def close(self):
        self.db.close()
