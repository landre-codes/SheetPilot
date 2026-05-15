import hashlib
import sqlite3
from pathlib import Path
from typing import Optional


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self):
        self.conn = sqlite3.connect(self.db_path, timeout=60)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=60000")
        self.conn.execute("PRAGMA cache_size=-64000")
        self.conn.row_factory = sqlite3.Row
        return self.conn

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def run_migrations(self, migrations_dir: str):
        if not self.conn:
            self.connect()
        cursor = self.conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS _migrations (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL UNIQUE, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        applied = {row["filename"] for row in cursor.execute("SELECT filename FROM _migrations").fetchall()}
        mig_path = Path(migrations_dir)
        for f in sorted(mig_path.glob("*.sql")):
            if f.name not in applied:
                sql = f.read_text(encoding="utf-8")
                cursor.executescript(sql)
                cursor.execute("INSERT INTO _migrations (filename) VALUES (?)", (f.name,))
                self.conn.commit()
                print(f"  [migracao] aplicado: {f.name}")
        print(f"  [migracao] {len(applied)} migracoes ja aplicadas")

    def compute_schema_hash(self, colunas: list[str]) -> str:
        raw = "|".join(colunas).strip().lower()
        return hashlib.md5(raw.encode("utf-8")).hexdigest()
