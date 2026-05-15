import json
import re
from datetime import datetime

from src.storage.database import Database
from src.storage.raw_repo import RawRepo


class TransformEngine:
    def __init__(self, db: Database):
        self.db = db
        self.raw_repo = RawRepo(db)

    def unpivot_para_star_schema(self, schema_hash: str, coluna_data_regex: str = r"^\d{4}-\d{2}$"):
        """Transforma raw_data (formato largo com datas como colunas) em star schema."""
        print(f"  [transform] unpivot schema_hash={schema_hash[:8]}")

        dados = self.raw_repo.get_raw_por_hash(schema_hash, limit=50000)

        if not dados:
            print(f"  [transform] nenhum dado encontrado para hash {schema_hash[:8]}")
            return

        colunas_originais = set()
        for row in dados:
            row_data = json.loads(row["row_data"])
            colunas_originais.update(row_data.keys())

        colunas_data = [c for c in colunas_originais if re.match(coluna_data_regex, c.strip())]
        colunas_fixas = [c for c in colunas_originais if c not in colunas_data]

        print(f"    colunas fixas: {len(colunas_fixas)}, colunas-data: {len(colunas_data)}")

        conn = self.db.conn
        c = conn.cursor()

        for dado in dados:
            row_data = json.loads(dado["row_data"])
            linha_id = dado["linha_id"]
            sheet_row = c.execute(
                "SELECT nome_sheet FROM sheets WHERE id = ?", (dado["sheet_id"],)
            ).fetchone()
            sheet_name = sheet_row["nome_sheet"] if sheet_row else ""

            arquivo_row = c.execute(
                "SELECT nome_arquivo FROM arquivos WHERE id = ?", (dado["arquivo_id"],)
            ).fetchone()
            nome_arquivo = arquivo_row["nome_arquivo"] if arquivo_row else "desconhecido"

            dim_arquivo_id = self._upsert_dim_arquivo(c, nome_arquivo, dado["arquivo_id"])
            self._processar_linha(c, dim_arquivo_id, schema_hash, sheet_name, linha_id, row_data, colunas_fixas,
                                  colunas_data)

        conn.commit()
        print(f"  [transform] unpivot concluido para {len(dados)} linhas")

    def processar_planilha_invertida(self, schema_hash: str, coluna_id_linha: str = "Cliente",
                                     coluna_data_regex: str = r"\d{4}"):
        """Processa planilha onde linhas = entidades, colunas = periodos."""
        print(f"  [transform] processando planilha invertida hash={schema_hash[:8]}")
        dados = self.raw_repo.get_raw_por_hash(schema_hash, limit=50000)

        if not dados:
            return

        conn = self.db.conn
        c = conn.cursor()

        for dado in dados:
            row_data = json.loads(dado["row_data"])
            linha_id = dado["linha_id"]
            sheet_row = c.execute(
                "SELECT nome_sheet FROM sheets WHERE id = ?", (dado["sheet_id"],)
            ).fetchone()
            sheet_name = sheet_row["nome_sheet"] if sheet_row else ""

            arquivo_row = c.execute(
                "SELECT nome_arquivo FROM arquivos WHERE id = ?", (dado["arquivo_id"],)
            ).fetchone()
            nome_arquivo = arquivo_row["nome_arquivo"] if arquivo_row else "desconhecido"

            dim_arquivo_id = self._upsert_dim_arquivo(c, nome_arquivo, dado["arquivo_id"])

            entidade = str(row_data.get(coluna_id_linha, f"linha_{linha_id}"))

            for coluna, valor in row_data.items():
                if coluna == coluna_id_linha:
                    continue
                if re.search(coluna_data_regex, coluna):
                    data_id = self._upsert_dim_data(c, coluna)
                    coluna_id = self._upsert_dim_coluna(c, schema_hash, coluna_id_linha, coluna_id_linha, "texto")
                    self._inserir_fact(c, dim_arquivo_id, data_id, coluna_id, schema_hash, sheet_name, linha_id, valor)

        conn.commit()
        print(f"  [transform] concluido: {len(dados)} linhas processadas")

    def _upsert_dim_arquivo(self, c, nome_arquivo, arquivo_id_db):
        caminho = f"db://{arquivo_id_db}"
        c.execute("""
                  INSERT INTO dim_arquivo (nome_arquivo, caminho_completo)
                  VALUES (?, ?) ON CONFLICT(caminho_completo) DO NOTHING
                  """, (nome_arquivo, caminho))
        row = c.execute("SELECT id FROM dim_arquivo WHERE caminho_completo = ?", (caminho,)).fetchone()
        return row["id"]

    def _upsert_dim_data(self, c, data_str):
        data_str = data_str.strip().replace("/", "-")
        try:
            if re.match(r"^\d{4}$", data_str):
                dt = datetime(int(data_str), 1, 1)
            elif re.match(r"^\d{4}-\d{2}$", data_str):
                partes = data_str.split("-")
                dt = datetime(int(partes[0]), int(partes[1]), 1)
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", data_str):
                dt = datetime.strptime(data_str, "%Y-%m-%d")
            else:
                return None
        except ValueError:
            return None

        data_str_full = dt.strftime("%Y-%m-%d")
        c.execute("""
                  INSERT INTO dim_data (data_completa, ano, mes, dia, trimestre, nome_mes, dia_semana)
                  VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(data_completa) DO NOTHING
                  """, (data_str_full, dt.year, dt.month, dt.day, (dt.month - 1) // 3 + 1,
                        dt.strftime("%B"), dt.weekday()))
        row = c.execute("SELECT id FROM dim_data WHERE data_completa = ?", (data_str_full,)).fetchone()
        return row["id"] if row else None

    def _upsert_dim_coluna(self, c, schema_hash, nome_original, nome_normalizado, tipo):
        import unicodedata
        if not nome_normalizado:
            nome_normalizado = nome_original
        nome_normalizado = unicodedata.normalize("NFKD", nome_normalizado).encode("ASCII", "ignore").decode("ASCII")
        nome_normalizado = re.sub(r"[^a-zA-Z0-9_]", "_", nome_normalizado).lower()

        c.execute("""
                  INSERT INTO dim_coluna (schema_hash, nome_coluna_original, nome_coluna_normalizado, tipo_dado)
                  VALUES (?, ?, ?, ?) ON CONFLICT(schema_hash, nome_coluna_original) DO NOTHING
                  """, (schema_hash, nome_original, nome_normalizado, tipo))
        row = c.execute(
            "SELECT id FROM dim_coluna WHERE schema_hash = ? AND nome_coluna_original = ?",
            (schema_hash, nome_original)
        ).fetchone()
        return row["id"] if row else None

    def _inserir_fact(self, c, dim_arquivo_id, data_id, coluna_id, schema_hash, sheet_name, linha_id, valor):
        if valor == "" or valor is None:
            return

        valor_texto = str(valor) if not isinstance(valor, (int, float)) else None
        valor_numerico = float(valor) if isinstance(valor, (int, float)) else None
        valor_data = None

        if isinstance(valor, str):
            for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y-%m"]:
                try:
                    valor_data = datetime.strptime(valor[:10], fmt).isoformat()
                    break
                except ValueError:
                    pass
            if valor_numerico is None and not valor_texto:
                valor_texto = valor

        c.execute("""
                  INSERT INTO fact_dados (arquivo_id, data_id, coluna_id, schema_hash, sheet_name, linha_origem,
                                          valor_texto, valor_numerico, valor_data)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                  """,
                  (dim_arquivo_id, data_id, coluna_id, schema_hash, sheet_name, linha_id, valor_texto, valor_numerico,
                   valor_data))

    def _processar_linha(self, c, dim_arquivo_id, schema_hash, sheet_name, linha_id, row_data, colunas_fixas,
                         colunas_data):
        """Unpivot: cada coluna-data vira uma linha em fact_dados.
        Colunas fixas (entidade) também são armazenadas (sem data_id)."""

        # Armazena colunas fixas (ex: "Região", "Cliente") para preservar a entidade
        for col_fixa in colunas_fixas:
            valor = row_data.get(col_fixa)
            if valor is None or valor == "":
                continue
            tipo = "texto" if isinstance(valor, str) else "numerico"
            coluna_id = self._upsert_dim_coluna(c, schema_hash, col_fixa, col_fixa, tipo)
            self._inserir_fact(c, dim_arquivo_id, None, coluna_id, schema_hash, sheet_name, linha_id, valor)

        for col_data in colunas_data:
            data_id = self._upsert_dim_data(c, col_data)
            if data_id is None:
                continue

            valor_data = row_data.get(col_data)
            if valor_data is None or valor_data == "":
                continue

            coluna_id = self._upsert_dim_coluna(c, schema_hash, col_data, col_data, "numerico")
            self._inserir_fact(c, dim_arquivo_id, data_id, coluna_id, schema_hash, sheet_name, linha_id, valor_data)
