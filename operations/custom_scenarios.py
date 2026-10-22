"""Persist newly generated errors so every API, worker and generator can replay them."""

import os
from pathlib import Path
import re
import sqlite3
import uuid

from utils.time_utils import now_iso

CODE_PATTERN = re.compile(r"\bNEW_ERROR_[A-F0-9]{8}_[A-F0-9]{4}_[A-F0-9]{4}_[A-F0-9]{4}_[A-F0-9]{12}\b")


class CustomScenarioStore:
    def __init__(self):
        directory = Path(os.getenv("LEARNED_SCRIPT_STATE_DIR", "learned-script-state"))
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "scenarios.sqlite"
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS scenarios (
                key TEXT PRIMARY KEY, error_code TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL, created_at TEXT NOT NULL
            )""")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def create(self, request_id=None):
        if request_id is None:
            identity = uuid.uuid4()
        else:
            try:
                identity = uuid.UUID(request_id)
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("invalid request_id") from exc
        key = "custom_" + identity.hex
        code = "NEW_ERROR_" + str(identity).replace("-", "_").upper()
        label = "신규 오류 (" + code + ")"
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO scenarios VALUES (?,?,?,?)", (key, code, label, now_iso()))
            return dict(db.execute("SELECT * FROM scenarios WHERE key=?", (key,)).fetchone())

    def list(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM scenarios ORDER BY created_at, key")]

    def find_code(self, code):
        with self.connect() as db:
            row = db.execute("SELECT * FROM scenarios WHERE error_code=?", (code,)).fetchone()
        return dict(row) if row else None


def custom_error_code(message):
    match = CODE_PATTERN.search(message)
    if match and CustomScenarioStore().find_code(match.group()):
        return match.group()
    return None
