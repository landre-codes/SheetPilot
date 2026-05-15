import json

from src.storage.database import Database


class RawRepo:
    def __init__(self, db: Database):
        self.db = db

    def inserir_linha(self, arquivo_id, sheet_id, linha_id, schema_hash, row_data: dict):
        c = self.db.conn.cursor()
        c.execute("""
                  INSERT INTO raw_data (arquivo_id, sheet_id, linha_id, schema_hash, row_data)
                  VALUES (?, ?, ?, ?, ?)
                  """, (arquivo_id, sheet_id, linha_id, schema_hash, json.dumps(row_data, ensure_ascii=False)))

    def inserir_em_lote(self, rows: list[tuple]):
        c = self.db.conn.cursor()
        c.executemany("""
                      INSERT INTO raw_data (arquivo_id, sheet_id, linha_id, schema_hash, row_data)
                      VALUES (?, ?, ?, ?, ?)
                      """, rows)
        self.db.conn.commit()

    def get_raw_por_sheet(self, sheet_id, limit=1000):
        c = self.db.conn.cursor()
        return c.execute("""
                         SELECT *
                         FROM raw_data
                         WHERE sheet_id = ?
                         ORDER BY linha_id LIMIT ?
                         """, (sheet_id, limit)).fetchall()

    def get_raw_por_hash(self, schema_hash, limit=1000):
        c = self.db.conn.cursor()
        return c.execute("""
                         SELECT *
                         FROM raw_data
                         WHERE schema_hash = ?
                         ORDER BY linha_id LIMIT ?
                         """, (schema_hash, limit)).fetchall()
