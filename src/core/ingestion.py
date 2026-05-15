import json, re
from pathlib import Path
from openpyxl import load_workbook
from src.storage.database import Database
from src.storage.metadata_repo import MetadataRepo
from src.storage.raw_repo import RawRepo


class IngestionEngine:
    def __init__(self, db: Database):
        self.db = db
        self.meta_repo = MetadataRepo(db)
        self.raw_repo = RawRepo(db)
        self._cache_grupos: dict[str, list] = {}  # (arquivo_id, parent_sheet) -> grupos

    @staticmethod
    def _detectar_grupos(linhas: list, min_linhas: int = 3) -> list[list]:
        """Divide linhas em grupos separados por linhas em branco. (mesma lógica do Discovery)"""
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
            if fim - inicio >= min_linhas:
                grupos.append(linhas[inicio:fim])
        return grupos

    def _extrair_grupo_por_indice(self, arquivo_id: int, parent_sheet: str, grupo_idx: int, wb) -> list:
        """Extrai um grupo específico de uma sheet, usando blank-row detection."""
        import hashlib
        cache_key = f"{arquivo_id}|{parent_sheet}"
        if cache_key not in self._cache_grupos:
            ws = wb[parent_sheet]
            linhas = list(ws.iter_rows(values_only=True))
            self._cache_grupos[cache_key] = self._detectar_grupos(linhas, min_linhas=3)

        grupos = self._cache_grupos[cache_key]
        if 0 <= grupo_idx < len(grupos):
            return grupos[grupo_idx]
        return []

    def ingestir_arquivo(self, caminho: str):
        path = Path(caminho)
        if not path.exists():
            print(f"  [erro] arquivo nao encontrado: {caminho}")
            return

        abs_path = str(path.absolute())
        arquivo_row = self.db.conn.execute(
            "SELECT id FROM arquivos WHERE caminho_completo = ?", (abs_path,)
        ).fetchone()

        if not arquivo_row:
            print(f"  [erro] arquivo nao scaneado: {caminho}. Execute scan primeiro.")
            return

        arquivo_id = arquivo_row["id"]
        sheets = self.meta_repo.get_sheets_por_arquivo(arquivo_id)

        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as e:
            print(f"  [erro] ao abrir {path.name}: {e}")
            self.meta_repo.atualizar_status_arquivo(arquivo_id, "erro")
            return

        total_linhas = 0
        self._cache_grupos.clear()

        for sheet_info in sheets:
            sheet_name = sheet_info["nome_sheet"]
            sheet_id = sheet_info["id"]
            schema_hash = sheet_info["schema_hash"]
            colunas = json.loads(sheet_info["schema_colunas"])

            # Verificar se é sub-tabela (ex: "Resumo_Geral__T001")
            m = re.match(r"^(.+)__T(\d+)$", sheet_name)
            if m:
                parent_name = m.group(1)
                grupo_idx = int(m.group(2)) - 1  # T001 → índice 0
                if parent_name not in wb.sheetnames:
                    continue
                linhas = self._extrair_grupo_por_indice(arquivo_id, parent_name, grupo_idx, wb)
                if not linhas:
                    print(f"    [ingest] {sheet_name}: grupo nao encontrado na sheet '{parent_name}'")
                    continue
            else:
                if sheet_name not in wb.sheetnames:
                    continue
                ws = wb[sheet_name]
                linhas = list(ws.iter_rows(values_only=True))

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
                        elif isinstance(valor, (float, int)):
                            valor = float(valor) if isinstance(valor, float) else valor
                        row_dict[nome_col] = valor
                batch.append((arquivo_id, sheet_id, idx, schema_hash,
                              json.dumps(row_dict, ensure_ascii=False, default=str)))

            if batch:
                self.raw_repo.inserir_em_lote(batch)
                total_linhas += len(batch)

            print(f"    [ingest] {sheet_name}: {len(batch)} linhas ingeridas")

        wb.close()
        self._cache_grupos.clear()
        self.meta_repo.atualizar_status_arquivo(arquivo_id, "ingerido")
        print(f"  [ingest] {path.name}: {total_linhas} linhas no total")
