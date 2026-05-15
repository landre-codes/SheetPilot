import json
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from src.storage.database import Database
from src.storage.metadata_repo import MetadataRepo


class DiscoveryEngine:
    def __init__(self, db: Database):
        self.db = db
        self.repo = MetadataRepo(db)
        self.detectar_tabelas = False
        self.min_linhas_tabela = 3

    def config(self, detectar_tabelas: bool = False, min_linhas: int = 3):
        self.detectar_tabelas = detectar_tabelas
        self.min_linhas_tabela = min_linhas

    def _detectar_grupos(self, linhas: list) -> list[list]:
        """Divide linhas em grupos separados por linhas em branco."""
        if not linhas:
            return []

        quebras = [-1]
        for i, row in enumerate(linhas):
            if all(c is None or str(c).strip() == "" for c in row):
                quebras.append(i)
        quebras.append(len(linhas))

        grupos = []
        for i in range(len(quebras) - 1):
            inicio = quebras[i] + 1
            fim = quebras[i + 1]
            if fim - inicio >= self.min_linhas_tabela:
                grupos.append(linhas[inicio:fim])

        return grupos

    def scan_arquivo(self, caminho: str):
        path = Path(caminho)
        if not path.exists():
            print(f"  [erro] arquivo nao encontrado: {caminho}")
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

        print(f"  [scan] {path.name} ({tamanho / 1024:.1f} KB)")

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

        arquivo_id = arquivo_row["id"]

        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as e:
            print(f"  [erro] ao abrir {path.name}: {e}")
            self.repo.atualizar_status_arquivo(arquivo_id, "erro")
            return

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            linhas = list(ws.iter_rows(values_only=True))
            if not linhas:
                continue

            # Detectar múltiplas tabelas separadas por linhas em branco
            if self.detectar_tabelas and len(linhas) > self.min_linhas_tabela:
                grupos = self._detectar_grupos(linhas)
                if len(grupos) <= 1:
                    grupos = [linhas]
            else:
                grupos = [linhas]

            for idx, grupo in enumerate(grupos):
                nome_tabela = f"{sheet_name}"
                if len(grupos) > 1:
                    nome_tabela = f"{sheet_name}__T{idx + 1:03d}"

                cabecalho = [str(c or "") for c in grupo[0]]
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
                            print(f"    [schema change] {nome_tabela}: +{len(adicionadas)} -{len(removidas)}")

                suffix = f" (tabela {idx + 1}/{len(grupos)})" if len(grupos) > 1 else ""
                print(
                    f"    [sheet] {nome_tabela}: {qtd_linhas} linhas x {qtd_colunas} colunas [hash={schema_hash[:8]}]{suffix}")

        wb.close()
        self.repo.atualizar_status_arquivo(arquivo_id, "scaneado")

    def scan_recursivo(self, diretorio: str):
        path = Path(diretorio)
        print(f"\n[discovery] escaneando: {diretorio}")
        xlsx_files = list(path.rglob("*.xlsx")) + list(path.rglob("*.xls"))
        print(f"  encontrados {len(xlsx_files)} arquivos")

        for f in xlsx_files:
            self.scan_arquivo(str(f))

        for f in xlsx_files:
            self.scan_sheets(str(f))

        print(f"  [discovery] concluido\n")
