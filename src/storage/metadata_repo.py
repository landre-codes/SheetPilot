from src.storage.database import Database
from src.log_setup import get_logger

logger = get_logger(__name__)


class MetadataRepo:
    def __init__(self, db: Database):
        self.db = db

    def upsert_arquivo(self, nome, caminho, ult_mod, tamanho):
        c = self.db.conn.cursor()
        try:
            c.execute("""
                      INSERT INTO arquivos (nome_arquivo, caminho_completo, ultima_modificacao, tamanho_bytes, status)
                      VALUES (?, ?, ?, ?, 'pendente') ON CONFLICT(caminho_completo) DO
                      UPDATE SET
                          ultima_modificacao = excluded.ultima_modificacao,
                          tamanho_bytes = excluded.tamanho_bytes,
                          status = CASE WHEN arquivos.ultima_modificacao IS DISTINCT
                      FROM excluded.ultima_modificacao THEN 'pendente' ELSE arquivos.status
                      END
                      """, (nome, caminho, ult_mod, tamanho))
            self.db.conn.commit()
        except Exception:
            self.db.conn.rollback()
            logger.error("Erro ao upsert arquivo: %s", caminho)
            raise

    def get_arquivos_pendentes(self):
        c = self.db.conn.cursor()
        return c.execute("SELECT * FROM arquivos WHERE status = 'pendente' ORDER BY id").fetchall()

    def get_sheets_por_arquivo(self, arquivo_id):
        c = self.db.conn.cursor()
        return c.execute("SELECT * FROM sheets WHERE arquivo_id = ?", (arquivo_id,)).fetchall()

    def upsert_sheet(self, arquivo_id, nome_sheet, colunas, tipos, qtd_linhas, qtd_colunas, schema_hash):
        c = self.db.conn.cursor()
        try:
            c.execute("""
                      INSERT INTO sheets (arquivo_id, nome_sheet, schema_hash, schema_colunas, schema_tipos, qtd_linhas,
                                          qtd_colunas, ultimo_hash_modificado)
                      VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(arquivo_id, nome_sheet) DO
                      UPDATE SET
                          schema_hash = excluded.schema_hash,
                          schema_colunas = excluded.schema_colunas,
                          schema_tipos = excluded.schema_tipos,
                          qtd_linhas = excluded.qtd_linhas,
                          qtd_colunas = excluded.qtd_colunas,
                          ultimo_hash_modificado = CURRENT_TIMESTAMP
                      """, (arquivo_id, nome_sheet, schema_hash, colunas, tipos, qtd_linhas, qtd_colunas))
            self.db.conn.commit()
            return c.lastrowid
        except Exception:
            self.db.conn.rollback()
            logger.error("Erro ao upsert sheet: %s / %s", nome_sheet, schema_hash[:8] if schema_hash else "")
            raise

    def arquivar_schema_change(self, sheet_id, hash_anterior, hash_novo, adicionadas, removidas):
        c = self.db.conn.cursor()
        import json
        try:
            c.execute("""
                      INSERT INTO schema_audit (sheet_id, schema_hash_anterior, schema_hash_novo, colunas_adicionadas,
                                                colunas_removidas)
                      VALUES (?, ?, ?, ?, ?)
                      """, (sheet_id, hash_anterior, hash_novo, json.dumps(adicionadas), json.dumps(removidas)))
            self.db.conn.commit()
        except Exception:
            self.db.conn.rollback()
            logger.error("Erro ao arquivar schema change: sheet_id=%s", sheet_id)
            raise

    def atualizar_status_arquivo(self, arquivo_id, status):
        c = self.db.conn.cursor()
        try:
            c.execute("UPDATE arquivos SET status = ? WHERE id = ?", (status, arquivo_id))
            self.db.conn.commit()
        except Exception:
            self.db.conn.rollback()
            logger.error("Erro ao atualizar status do arquivo: id=%s, status=%s", arquivo_id, status)
            raise
