import json
import re
from datetime import datetime

from src.log_setup import get_logger
from src.storage.database import Database
from src.storage.raw_repo import RawRepo

logger = get_logger(__name__)

# Regex padrao para deteccao de colunas-data nos formatos:
#   dd/mm/aaaa (predominante), mm/aaaa, dd-mm-aaaa, aaaa-mm-dd, aaaa-mm, aaaa
COLUNA_DATA_REGEX_DEFAULT = (
    r"^(?:\d{2}[/-]\d{2}[/-]\d{4}"  # dd/mm/aaaa ou dd-mm-aaaa
    r"|\d{2}[/-]\d{4}"  # mm/aaaa ou mm-aaaa
    r"|\d{4}[/-]\d{2}(?:[/-]\d{2})?"  # aaaa-mm ou aaaa-mm-dd
    r"|\d{4})$"  # apenas ano (ex: 2025)
)

# Formatos de data suportados para parse de valores (amostras)
_DATA_FORMATS = [
    ("%d/%m/%Y", r"^\d{2}/\d{2}/\d{4}$"),
    ("%d-%m-%Y", r"^\d{2}-\d{2}-\d{4}$"),
    ("%Y-%m-%d", r"^\d{4}-\d{2}-\d{2}$"),
    ("%m/%Y", r"^\d{2}/\d{4}$"),
    ("%m-%Y", r"^\d{2}-\d{4}$"),
    ("%Y-%m", r"^\d{4}-\d{2}$"),
    ("%Y", r"^\d{4}$"),
]

_BATCH_SIZE = 5000


class TransformEngine:
    def __init__(self, db: Database):
        self.db = db
        self.raw_repo = RawRepo(db)

    def unpivot_para_star_schema(self, schema_hash: str,
                                 coluna_data_regex: str = COLUNA_DATA_REGEX_DEFAULT):
        """Transforma raw_data (formato largo com datas como colunas) em star schema."""
        logger.info("Unpivot schema_hash=%s...", schema_hash[:8])

        # Determinar colunas a partir da primeira linha (todas têm as mesmas colunas)
        primeira = self.raw_repo.get_raw_por_hash(schema_hash, limit=1)
        if not primeira:
            logger.warning("Nenhum dado encontrado para hash=%s", schema_hash[:8])
            return

        colunas_originais = set(json.loads(primeira[0]["row_data"]).keys())

        colunas_candidatas = [c for c in colunas_originais if re.match(coluna_data_regex, c.strip())]
        logger.debug("Total colunas=%d, candidatas a data=%d",
                     len(colunas_originais), len(colunas_candidatas))

        # Validar por amostras (amostra do início dos dados)
        if colunas_candidatas:
            amostras_dados = self.raw_repo.get_raw_por_hash(schema_hash, limit=500)
            colunas_data = list(
                TransformEngine._amostrar_valores_data(amostras_dados, colunas_candidatas)
            ) if amostras_dados else colunas_candidatas
        else:
            colunas_data = []

        colunas_fixas = [c for c in colunas_originais if c not in colunas_data]
        logger.info("Colunas fixas=%d, colunas data=%d", len(colunas_fixas), len(colunas_data))

        if not colunas_fixas:
            logger.warning("Nenhuma coluna fixa encontrada! schema_hash=%s. "
                           "Verifique se a regex de datas nao esta muito abrangente.",
                           schema_hash[:8])

        # Processar em batches com colunas pré-definidas
        total_processado = 0
        offset = 0
        while True:
            dados = self.raw_repo.get_raw_por_hash(schema_hash, limit=_BATCH_SIZE, offset=offset)
            if not dados:
                break
            total_processado += self._processar_lote_fixo(
                schema_hash, dados, colunas_fixas, colunas_data
            )
            offset += _BATCH_SIZE
            logger.debug("Unpivot progresso: %d linhas", total_processado)

        logger.info("Unpivot concluido para hash=%s (%d linhas)", schema_hash[:8], total_processado)

    @staticmethod
    def _amostrar_valores_data(dados: list, colunas_candidatas: list[str],
                               min_amostras: int = 5, limiar: float = 0.7) -> set[str]:
        """Amostra valores reais de colunas candidatas a data para validar.
        Regras:
        - Numeros sao neutros (nao confirmam, nao rejeitam)
        - Strings que parseiam como data -> acerto
        - Strings que NAO parseiam como data -> erro
        So rejeita coluna se a maioria das amostras NAO neutras for erro."""
        if not colunas_candidatas:
            return set()

        amostras: dict[str, list] = {}
        for row in dados:
            row_data = json.loads(row["row_data"])
            for col in colunas_candidatas:
                val = row_data.get(col)
                if val is not None and str(val).strip():
                    amostras.setdefault(col, []).append(val)

        confirmadas: set[str] = set()
        for col, vals in amostras.items():
            vals_unicos = list(dict.fromkeys(str(v) for v in vals))
            amostra = vals_unicos[:min_amostras]
            if not amostra:
                continue
            acertos = 0
            erros = 0
            neutros = 0
            for v in amostra:
                v = str(v).strip()
                # Numerico/float -> neutro (inverted tables tem valores numericos)
                try:
                    float(v)
                    neutros += 1
                    continue
                except ValueError:
                    pass
                if not v:
                    neutros += 1
                    continue
                parsed = False
                for fmt, pattern in _DATA_FORMATS:
                    if re.match(pattern, v):
                        try:
                            datetime.strptime(v, fmt)
                            acertos += 1
                            parsed = True
                            break
                        except ValueError:
                            continue
                if not parsed:
                    erros += 1

            opiniao = acertos + erros
            if opiniao == 0:
                # Sem opiniao (so numeros) -> confia no regex (liberal)
                confirmadas.add(col)
                logger.debug("Coluna '%s': %d neutras, sem opiniao -> aceita", col, neutros)
            elif acertos / opiniao >= limiar:
                confirmadas.add(col)
                logger.debug("Coluna '%s': %d/%d opinioes sao datas -> aceita", col, acertos, opiniao)
            elif neutros >= 3 and erros <= 1:
                # Maioria neutra com poucos erros -> provavelmente coluna data com falhas isoladas
                confirmadas.add(col)
                logger.debug("Coluna '%s': %d neutras, %d/%d opinioes -> aceita (tolerancia)", col, neutros, acertos,
                             opiniao)
            else:
                logger.debug("Coluna '%s': apenas %d/%d opinioes sao datas -> rejeitada", col, acertos, opiniao)

        return confirmadas

    def _processar_lote(self, schema_hash: str, dados: list, coluna_data_regex: str) -> int:
        """Legacy: detecta colunas por batch (mantido para compatibilidade)."""
        colunas_originais = set()
        for row in dados:
            row_data = json.loads(row["row_data"])
            colunas_originais.update(row_data.keys())

        colunas_candidatas = [c for c in colunas_originais if re.match(coluna_data_regex, c.strip())]
        if colunas_candidatas and dados:
            colunas_data = list(self._amostrar_valores_data(dados, colunas_candidatas))
        else:
            colunas_data = colunas_candidatas

        colunas_fixas = [c for c in colunas_originais if c not in colunas_data]

        if not colunas_fixas:
            logger.warning("Nenhuma coluna fixa encontrada! schema_hash=%s.", schema_hash[:8])

        logger.debug("Lote (legacy): %d linhas, %d fixas, %d data columns",
                     len(dados), len(colunas_fixas), len(colunas_data))
        return self._processar_lote_fixo(schema_hash, dados, colunas_fixas, colunas_data)

    def _processar_lote_fixo(self, schema_hash: str, dados: list,
                             colunas_fixas: list[str], colunas_data: list[str]) -> int:
        """Processa um lote com colunas fixas e de data já determinadas.
        
        Elimina N+1 queries: faz um JOIN único para resolver nomes de sheet e arquivo
        para todas as linhas do lote de uma só vez, armazenando em dicts em memória.
        """
        conn = self.db.conn
        c = conn.cursor()
        processadas = 0

        # Resolve nomes para todo o lote em 2 queries (em vez de N queries)
        sheet_ids = {d["sheet_id"] for d in dados}
        arquivo_ids = {d["arquivo_id"] for d in dados}

        sheet_map = {}
        if sheet_ids:
            placeholders = ",".join("?" * len(sheet_ids))
            for row in c.execute(
                f"SELECT id, nome_sheet FROM sheets WHERE id IN ({placeholders})",
                tuple(sheet_ids),
            ):
                sheet_map[row["id"]] = row["nome_sheet"]

        arquivo_map = {}
        if arquivo_ids:
            placeholders = ",".join("?" * len(arquivo_ids))
            for row in c.execute(
                f"SELECT id, nome_arquivo FROM arquivos WHERE id IN ({placeholders})",
                tuple(arquivo_ids),
            ):
                arquivo_map[row["id"]] = row["nome_arquivo"]

        try:
            for dado in dados:
                row_data = json.loads(dado["row_data"])
                linha_id = dado["linha_id"]
                sheet_name = sheet_map.get(dado["sheet_id"], "")
                nome_arquivo = arquivo_map.get(dado["arquivo_id"], "desconhecido")

                dim_arquivo_id = self._upsert_dim_arquivo(c, nome_arquivo, dado["arquivo_id"])
                self._processar_linha(c, dim_arquivo_id, schema_hash, sheet_name, linha_id,
                                      row_data, colunas_fixas, colunas_data)
                processadas += 1

            conn.commit()
        except Exception:
            conn.rollback()
            logger.error("Erro no lote fixo (schema_hash=%s)", schema_hash[:8])
            raise
        return processadas

    def processar_planilha_invertida(self, schema_hash: str, coluna_id_linha: str = "Cliente",
                                     coluna_data_regex: str = COLUNA_DATA_REGEX_DEFAULT):
        """Processa planilha onde linhas = entidades, colunas = periodos."""
        logger.info("Processando planilha invertida hash=%s", schema_hash[:8])

        total_processado = 0
        offset = 0

        while True:
            dados = self.raw_repo.get_raw_por_hash(schema_hash, limit=_BATCH_SIZE, offset=offset)
            if not dados:
                break

            conn = self.db.conn
            c = conn.cursor()
            processadas = 0

            # Resolve nomes para todo o lote (elimina N+1)
            sheet_ids = {d["sheet_id"] for d in dados}
            arquivo_ids = {d["arquivo_id"] for d in dados}
            sheet_map = {}
            if sheet_ids:
                placeholders = ",".join("?" * len(sheet_ids))
                for row in c.execute(
                    f"SELECT id, nome_sheet FROM sheets WHERE id IN ({placeholders})",
                    tuple(sheet_ids),
                ):
                    sheet_map[row["id"]] = row["nome_sheet"]
            arquivo_map = {}
            if arquivo_ids:
                placeholders = ",".join("?" * len(arquivo_ids))
                for row in c.execute(
                    f"SELECT id, nome_arquivo FROM arquivos WHERE id IN ({placeholders})",
                    tuple(arquivo_ids),
                ):
                    arquivo_map[row["id"]] = row["nome_arquivo"]

            try:
                for dado in dados:
                    row_data = json.loads(dado["row_data"])
                    linha_id = dado["linha_id"]
                    sheet_name = sheet_map.get(dado["sheet_id"], "")
                    nome_arquivo = arquivo_map.get(dado["arquivo_id"], "desconhecido")

                    dim_arquivo_id = self._upsert_dim_arquivo(c, nome_arquivo, dado["arquivo_id"])

                    for coluna, valor in row_data.items():
                        if coluna == coluna_id_linha:
                            continue
                        if re.fullmatch(coluna_data_regex, coluna.strip()):
                            data_id = self._upsert_dim_data(c, coluna)
                            coluna_id = self._upsert_dim_coluna(c, schema_hash, coluna_id_linha,
                                                                coluna_id_linha, "texto")
                            self._inserir_fact(c, dim_arquivo_id, data_id, coluna_id,
                                               schema_hash, sheet_name, linha_id, valor)

                    processadas += 1

                conn.commit()
            except Exception:
                conn.rollback()
                logger.error("Erro no lote de planilha invertida (hash=%s, offset=%d)",
                             schema_hash[:8], offset)
                raise

            total_processado += processadas
            offset += _BATCH_SIZE

        logger.info("Planilha invertida concluida: %d linhas", total_processado)

    def _upsert_dim_arquivo(self, c, nome_arquivo, arquivo_id_db):
        caminho = "db://{}".format(arquivo_id_db)
        c.execute("""
                  INSERT INTO dim_arquivo (nome_arquivo, caminho_completo)
                  VALUES (?, ?) ON CONFLICT(caminho_completo) DO NOTHING
                  """, (nome_arquivo, caminho))
        row = c.execute("SELECT id FROM dim_arquivo WHERE caminho_completo = ?", (caminho,)).fetchone()
        return row["id"] if row else None

    def _upsert_dim_data(self, c, data_str):
        """Converte string de data para chave em dim_data.
        Formatos aceitos: dd/mm/aaaa, dd-mm-aaaa, mm/aaaa, mm-aaaa,
                          aaaa-mm-dd, aaaa-mm, aaaa
        Retorna o id da dim_data ou None se nao for possivel interpretar.
        """
        data_str = data_str.strip().replace("/", "-")
        try:
            if re.match(r"^\d{4}$", data_str):
                dt = datetime(int(data_str), 1, 1)
            elif re.match(r"^\d{4}-\d{2}$", data_str):
                partes = data_str.split("-")
                dt = datetime(int(partes[0]), int(partes[1]), 1)
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", data_str):
                dt = datetime.strptime(data_str, "%Y-%m-%d")
            elif re.match(r"^\d{2}-\d{2}-\d{4}$", data_str):
                partes = data_str.split("-")
                dt = datetime(int(partes[2]), int(partes[1]), int(partes[0]))
            elif re.match(r"^\d{2}-\d{4}$", data_str):
                partes = data_str.split("-")
                dt = datetime(int(partes[1]), int(partes[0]), 1)
            else:
                logger.debug("Formato de data nao reconhecido: %s", data_str)
                return None
        except ValueError:
            logger.warning("Valor de data invalido: %s", data_str)
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
        if valor == "" or valor is None or dim_arquivo_id is None or coluna_id is None:
            return

        if isinstance(valor, (int, float)):
            valor_texto = None
            valor_numerico = float(valor)
            valor_data = None
        else:
            valor_texto = str(valor)
            valor_numerico = None
            valor_data = None
            for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%m/%Y", "%Y-%m"]:
                try:
                    val_str = str(valor).strip()[:19]
                    valor_data = datetime.strptime(val_str, fmt).isoformat()
                    break
                except ValueError:
                    pass

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

        for col_fixa in colunas_fixas:
            valor = row_data.get(col_fixa)
            if valor is None or valor == "":
                continue
            tipo = "texto" if isinstance(valor, str) else "numerico"
            coluna_id = self._upsert_dim_coluna(c, schema_hash, col_fixa, col_fixa, tipo)
            self._inserir_fact(c, dim_arquivo_id, None, coluna_id, schema_hash, sheet_name, linha_id, valor)

        for col_data in colunas_data:
            data_id = self._upsert_dim_data(c, col_data)

            valor_data = row_data.get(col_data)
            if valor_data is None or valor_data == "":
                continue

            coluna_id = self._upsert_dim_coluna(c, schema_hash, col_data, col_data, "numerico")
            self._inserir_fact(c, dim_arquivo_id, data_id, coluna_id, schema_hash, sheet_name, linha_id, valor_data)
