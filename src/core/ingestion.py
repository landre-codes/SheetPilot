import json
import re
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from src.core.utils import detectar_grupos, iter_rows_lazy
from src.log_setup import get_logger
from src.storage.database import Database
from src.storage.metadata_repo import MetadataRepo
from src.storage.raw_repo import RawRepo

logger = get_logger(__name__)


class IngestionEngine:
    def __init__(self, db: Database):
        self.db = db
        self.meta_repo = MetadataRepo(db)
        self.raw_repo = RawRepo(db)
        self._cache_grupos: dict[str, list] = {}

    def _extrair_grupo_por_indice(self, arquivo_id: int, parent_sheet: str, grupo_idx: int, wb) -> list:
        """Extrai um grupo específico de uma sheet, lendo em chunks para evitar
        materialização completa na RAM."""
        cache_key = f"{arquivo_id}|{parent_sheet}"
        if cache_key not in self._cache_grupos:
            ws = wb[parent_sheet]
            linhas = []
            for chunk in iter_rows_lazy(ws, chunk_size=5000):
                linhas.extend(chunk)
            self._cache_grupos[cache_key] = detectar_grupos(linhas, min_linhas=3)

        grupos = self._cache_grupos[cache_key]
        if 0 <= grupo_idx < len(grupos):
            return grupos[grupo_idx]
        return []

    def ingestir_arquivo(self, caminho: str):
        path = Path(caminho)
        if not path.exists():
            logger.error("Arquivo nao encontrado: %s", caminho)
            return

        abs_path = str(path.absolute())
        arquivo_row = self.db.conn.execute(
            "SELECT id FROM arquivos WHERE caminho_completo = ?", (abs_path,)
        ).fetchone()

        if not arquivo_row:
            logger.error("Arquivo nao scaneado: %s. Execute scan primeiro.", caminho)
            return

        arquivo_id = arquivo_row["id"]
        sheets = self.meta_repo.get_sheets_por_arquivo(arquivo_id)

        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as e:
            logger.error("Erro ao abrir %s: %s", path.name, e)
            self.meta_repo.atualizar_status_arquivo(arquivo_id, "erro")
            return

        total_linhas = 0
        self._cache_grupos.clear()

        for sheet_info in sheets:
            sheet_name = sheet_info["nome_sheet"]
            sheet_id = sheet_info["id"]
            schema_hash = sheet_info["schema_hash"]
            colunas = json.loads(sheet_info["schema_colunas"])

            m = re.match(r"^(.+)__T(\d+)$", sheet_name)
            if m:
                parent_name = m.group(1)
                grupo_idx = int(m.group(2)) - 1
                if parent_name not in wb.sheetnames:
                    continue
                linhas = self._extrair_grupo_por_indice(arquivo_id, parent_name, grupo_idx, wb)
                if not linhas:
                    logger.warning("Grupo nao encontrado: %s na sheet '%s'", sheet_name, parent_name)
                    continue
            else:
                if sheet_name not in wb.sheetnames:
                    continue
                ws = wb[sheet_name]
                linhas = []
                for chunk in iter_rows_lazy(ws, chunk_size=5000):
                    linhas.extend(chunk)

            if len(linhas) <= 1:
                continue

            batch = []
            for idx, row in enumerate(linhas[1:], start=2):
                row_dict = {}
                for col_idx, valor in enumerate(row):
                    if col_idx < len(colunas):
                        nome_col = colunas[col_idx]
                        if valor is None:
                            valor = ""
                        elif isinstance(valor, datetime):
                            valor = valor.strftime("%Y-%m-%d")
                        elif isinstance(valor, (float, int)):
                            valor = float(valor) if isinstance(valor, float) else valor
                        row_dict[nome_col] = valor
                batch.append((arquivo_id, sheet_id, idx, schema_hash,
                              json.dumps(row_dict, ensure_ascii=False, default=str)))

            if batch:
                self.raw_repo.inserir_em_lote(batch)
                total_linhas += len(batch)

            logger.info("Ingerido %s: %d linhas", sheet_name, len(batch))

        wb.close()
        self._cache_grupos.clear()
        self.meta_repo.atualizar_status_arquivo(arquivo_id, "ingerido")
        logger.info("Ingestao de %s: %d linhas no total", path.name, total_linhas)
