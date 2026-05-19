import json

from src.log_setup import get_logger
from src.storage.database import Database

logger = get_logger(__name__)


class RawRepo:
    def __init__(self, db: Database):
        self.db = db

    def inserir_em_lote(self, rows: list[tuple]):
        c = self.db.conn.cursor()
        try:
            c.executemany("""
                          INSERT INTO raw_data (arquivo_id, sheet_id, linha_id, schema_hash, row_data)
                          VALUES (?, ?, ?, ?, ?)
                          """, rows)
            self.db.conn.commit()
        except Exception:
            self.db.conn.rollback()
            logger.error("Erro ao inserir lote de raw_data (%s linhas)", len(rows))
            raise

    def get_raw_por_sheet(self, sheet_id, limit=1000):
        c = self.db.conn.cursor()
        return c.execute("""
                         SELECT *
                         FROM raw_data
                         WHERE sheet_id = ?
                         ORDER BY linha_id LIMIT ?
                         """, (sheet_id, limit)).fetchall()

    def get_raw_por_hash(self, schema_hash, limit=1000, offset=0):
        c = self.db.conn.cursor()
        if len(schema_hash) == 32:
            sql = "SELECT * FROM raw_data WHERE schema_hash = ? ORDER BY linha_id LIMIT ? OFFSET ?"
            params = (schema_hash, limit, offset)
        else:
            sql = "SELECT * FROM raw_data WHERE schema_hash LIKE ? ORDER BY linha_id LIMIT ? OFFSET ?"
            params = (schema_hash + "%", limit, offset)
        return c.execute(sql, params).fetchall()
