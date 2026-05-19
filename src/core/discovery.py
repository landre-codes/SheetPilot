import json
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from src.core.utils import detectar_grupos, iter_rows_lazy, normalizar_cabecalho
from src.log_setup import get_logger
from src.storage.database import Database
from src.storage.metadata_repo import MetadataRepo

logger = get_logger(__name__)


class DiscoveryEngine:
    def __init__(self, db: Database):
        self.db = db
        self.repo = MetadataRepo(db)
        self.detectar_tabelas = False
        self.min_linhas_tabela = 3

    def config(self, detectar_tabelas: bool = False, min_linhas: int = 3):
        self.detectar_tabelas = detectar_tabelas
        self.min_linhas_tabela = min_linhas

    def scan_arquivo(self, caminho: str):
        path = Path(caminho)
        if not path.exists():
            logger.error("Arquivo nao encontrado: %s", caminho)
            return

        stats = path.stat()
        ult_mod = datetime.fromtimestamp(stats.st_mtime)
        tamanho = stats.st_size

        self.repo.upsert_arquivo(
            nome=path.name,
            caminho=str(path.absolute()),
            ult_mod=ult_mod,
            tamanho=tamanho
        )

        logger.info("Scanned %s (%.1f KB)", path.name, tamanho / 1024)

    def scan_sheets(self, caminho: str):
        path = Path(caminho)
        if not path.exists():
            return

        arquivo_row = self.db.conn.execute(
            "SELECT id FROM arquivos WHERE caminho_completo = ?", (str(path.absolute()),)
        ).fetchone()

        if not arquivo_row:
            self.scan_arquivo(caminho)
            arquivo_row = self.db.conn.execute(
                "SELECT id FROM arquivos WHERE caminho_completo = ?", (str(path.absolute()),)
            ).fetchone()

        if not arquivo_row:
            logger.error("Nao foi possivel criar registro para: %s", caminho)
            return
        arquivo_id = arquivo_row["id"]

        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as e:
            logger.error("Erro ao abrir %s: %s", path.name, e)
            self.repo.atualizar_status_arquivo(arquivo_id, "erro")
            return

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]

            # Lê todas as linhas em chunks para evitar materialização completa na RAM
            linhas = []
            for chunk in iter_rows_lazy(ws, chunk_size=5000):
                linhas.extend(chunk)
            if not linhas:
                continue

            # Detectar múltiplas tabelas separadas por linhas em branco
            if self.detectar_tabelas and len(linhas) > self.min_linhas_tabela:
                grupos = detectar_grupos(linhas, self.min_linhas_tabela)
                if len(grupos) <= 1:
                    grupos = [linhas]
            else:
                grupos = [linhas]

            for idx, grupo in enumerate(grupos):
                nome_tabela = f"{sheet_name}"
                if len(grupos) > 1:
                    nome_tabela = f"{sheet_name}__T{idx + 1:03d}"

                cabecalho = [normalizar_cabecalho(c) for c in grupo[0]]
                schema_hash = self.db.compute_schema_hash(cabecalho)
                colunas = json.dumps(cabecalho, ensure_ascii=False)
                tipos_inferidos = ["texto"] * len(cabecalho)
                qtd_linhas = len(grupo) - 1
                qtd_colunas = len(cabecalho)

                sheet_existente = self.db.conn.execute(
                    "SELECT id, schema_hash, schema_colunas FROM sheets WHERE arquivo_id = ? AND nome_sheet = ?",
                    (arquivo_id, nome_tabela)
                ).fetchone()

                sheet_id = self.repo.upsert_sheet(
                    arquivo_id, nome_tabela, colunas, json.dumps(tipos_inferidos),
                    qtd_linhas, qtd_colunas, schema_hash
                )

                if sheet_existente:
                    hash_anterior = sheet_existente["schema_hash"]
                    if hash_anterior and hash_anterior != schema_hash:
                        col_anteriores = set(json.loads(sheet_existente["schema_colunas"]))
                        col_novas = set(cabecalho)
                        adicionadas = list(col_novas - col_anteriores)
                        removidas = list(col_anteriores - col_novas)
                        self.repo.arquivar_schema_change(
                            sheet_id, hash_anterior, schema_hash,
                            adicionadas, removidas
                        )
                        if adicionadas or removidas:
                            logger.info("Schema change %s: +%d -%d", nome_tabela, len(adicionadas), len(removidas))

                suffix = f" (tabela {idx + 1}/{len(grupos)})" if len(grupos) > 1 else ""
                logger.info("Sheet %s: %d linhas x %d colunas [hash=%s]%s",
                            nome_tabela, qtd_linhas, qtd_colunas, schema_hash[:8], suffix)

        wb.close()
        self.repo.atualizar_status_arquivo(arquivo_id, "scaneado")

    def scan_recursivo(self, diretorio: str):
        path = Path(diretorio)
        logger.info("Escaneando: %s", diretorio)
        xlsx_files = []
        for ext in ["*.xlsx", "*.xlsb", "*.xlsm", "*.csv", "*.parquet"]:
            xlsx_files.extend(path.rglob(ext))
        logger.info("Encontrados %d arquivos", len(xlsx_files))

        for f in xlsx_files:
            self.scan_arquivo(str(f))

        for f in xlsx_files:
            self.scan_sheets(str(f))

        logger.info("Discovery concluido para: %s", diretorio)
