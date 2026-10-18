"""Small durable registry. One connection per operation; WAL allows concurrent reads."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    KINDS = {"datasets", "models", "jobs", "events"}

    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT PRIMARY KEY, created TEXT, body TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS records_kind_created ON records(kind, created DESC)")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def add(self, kind, body):
        assert kind in self.KINDS
        record = {**body, "id": uuid.uuid4().hex, "created": now()}
        with self.connect() as db:
            db.execute("INSERT INTO records VALUES (?, ?, ?, ?)",
                       (kind, record["id"], record["created"], json.dumps(record, allow_nan=False)))
        return record

    def get(self, kind, record_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return json.loads(row[0])

    def list(self, kind, limit=100):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM records WHERE kind=? ORDER BY created DESC LIMIT ?", (kind, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(self, kind, record_id, updates):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
            if row is None:
                raise KeyError(record_id)
            record = {**json.loads(row[0]), **updates}
            record["id"] = record_id
            db.execute("UPDATE records SET body=? WHERE kind=? AND id=?",
                       (json.dumps(record, allow_nan=False), kind, record_id))
        return record

    def summary(self):
        with self.connect() as db:
            counts = dict(db.execute("SELECT kind, COUNT(*) FROM records GROUP BY kind"))
            # All events count, not merely the latest dashboard page.
            open_events = db.execute("SELECT COUNT(*) FROM records WHERE kind='events' AND json_extract(body, '$.status')='open'").fetchone()[0]
        return {**{k: counts.get(k, 0) for k in self.KINDS}, "open_incidents": open_events}
