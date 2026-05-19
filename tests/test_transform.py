"""Testes para src.core.transform — especialmente _upsert_dim_data e o ciclo unpivot."""
import json
import re

import pytest

from src.core.transform import TransformEngine, COLUNA_DATA_REGEX_DEFAULT


# ─── Testes da regex de deteccao ─────────────────────────────────────────


class TestRegexDeteccao:
    """Verifica se a COLUNA_DATA_REGEX_DEFAULT casa corretamente os formatos de data."""

    _regex = re.compile(COLUNA_DATA_REGEX_DEFAULT)

    @pytest.mark.parametrize("header", [
        "15/01/2025",
        "01/12/2024",
        "31/01/2023",
        "15-01-2025",
        "01-12-2024",
    ])
    def test_deve_casar_dd_mm_aaaa(self, header):
        assert self._regex.match(header), f"Devia casar: {header}"

    @pytest.mark.parametrize("header", [
        "01/2025",
        "12/2024",
        "01-2025",
        "12-2024",
    ])
    def test_deve_casar_mm_aaaa(self, header):
        assert self._regex.match(header), f"Devia casar: {header}"

    @pytest.mark.parametrize("header", [
        "2025-01",
        "2024-12",
        "2025/01",
    ])
    def test_deve_casar_aaaa_mm(self, header):
        assert self._regex.match(header), f"Devia casar: {header}"

    @pytest.mark.parametrize("header", [
        "2025-01-15",
        "2024-12-01",
    ])
    def test_deve_casar_aaaa_mm_dd(self, header):
        assert self._regex.match(header), f"Devia casar: {header}"

    @pytest.mark.parametrize("header", [
        "2025",
        "2024",
        "1999",
    ])
    def test_deve_casar_ano(self, header):
        assert self._regex.match(header), f"Devia casar: {header}"

    @pytest.mark.parametrize("header", [
        "Cliente",
        "Regiao",
        "Produto A",
        "ID_123",
        "",
        "01/25",
        "Nota Fiscal",
        "15/01/25",  # ano com 2 digitos
    ])
    def test_nao_deve_casar_nao_data(self, header):
        assert not self._regex.match(header), f"Nao devia casar: {header}"


# ─── Testes da amostragem de valores ────────────────────────────────────


class TestAmostragemValoresData:
    """Verifica se a amostragem de valores confirma/rejeita colunas candidatas."""

    def test_confirma_data_pelo_valor(self):
        dados = [
            {"row_data": json.dumps({"Cliente": "Joao", "15/01/2025": 1000})},
            {"row_data": json.dumps({"Cliente": "Maria", "16/01/2025": 2000})},
        ]
        confirmadas = TransformEngine._amostrar_valores_data(dados, ["15/01/2025"])
        assert "15/01/2025" in confirmadas

    def test_rejeita_coluna_com_valores_nao_data(self):
        dados = [
            {"row_data": json.dumps({"2025": "ABC-123"})},
            {"row_data": json.dumps({"2025": "XYZ-789"})},
        ]
        confirmadas = TransformEngine._amostrar_valores_data(dados, ["2025"])
        assert "2025" not in confirmadas

    def test_confirma_mesmo_com_mistura(self):
        """Se a maioria dos valores nao neutros for data, confirma."""
        dados = [
            {"row_data": json.dumps({"01/2025": "15/01/2025"})},
            {"row_data": json.dumps({"01/2025": "N/D"})},
            {"row_data": json.dumps({"01/2025": "20/01/2025"})},
        ]
        confirmadas = TransformEngine._amostrar_valores_data(dados, ["01/2025"], limiar=0.5)
        assert "01/2025" in confirmadas

    def test_formato_mm_aaaa_com_valores_numericos(self):
        """Valores numericos sao neutros — coluna deve ser aceita."""
        dados = [
            {"row_data": json.dumps({"Cliente": "Joao", "01/2025": 1000})},
        ]
        confirmadas = TransformEngine._amostrar_valores_data(dados, ["01/2025"])
        assert "01/2025" in confirmadas

    def test_aceita_coluna_com_maioria_neutra_e_um_erro(self):
        """Coluna com 4 neutros e 1 string nao-data deve ser aceita (tolerancia)."""
        dados = [
            {"row_data": json.dumps({"01/2025": v})}
            for v in [1000, 2000, 3000, 4000, "N/D"]
        ]
        confirmadas = TransformEngine._amostrar_valores_data(dados, ["01/2025"])
        assert "01/2025" in confirmadas

    def test_rejeita_coluna_com_varios_erros_sem_neutros(self):
        """Coluna com multiplas strings nao-data e sem neutros deve ser rejeitada."""
        dados = [
            {"row_data": json.dumps({"Col": v})}
            for v in ["ABC", "DEF", "GHI", "JKL", "MNO"]
        ]
        confirmadas = TransformEngine._amostrar_valores_data(dados, ["Col"])
        assert "Col" not in confirmadas

    def test_aceita_coluna_com_datetime_iso_string(self):
        """Coluna com valores ISO 'YYYY-MM-DD' (de datetime normalizado) deve ser aceita."""
        dados = [
            {"row_data": json.dumps({"2025-01-10": v})}
            for v in [1000, 2000, 3000, "2025-01-10", "2025-01-11"]
        ]
        confirmadas = TransformEngine._amostrar_valores_data(dados, ["2025-01-10"])
        assert "2025-01-10" in confirmadas


# ─── Testes do _upsert_dim_data ─────────────────────────────────────────


class TestUpsertDimData:
    """Testa a conversao de strings de data para registros em dim_data."""

    def _upsert(self, engine, cursor, data_str):
        return engine._upsert_dim_data(cursor, data_str)

    def test_dd_mm_aaaa_com_barra(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        data_id = self._upsert(engine, c, "15/01/2025")
        assert data_id is not None
        row = c.execute("SELECT * FROM dim_data WHERE id = ?", (data_id,)).fetchone()
        assert row["data_completa"] == "2025-01-15"
        assert row["ano"] == 2025
        assert row["mes"] == 1
        assert row["dia"] == 15

    def test_dd_mm_aaaa_com_hifen(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        data_id = self._upsert(engine, c, "15-01-2025")
        assert data_id is not None
        row = c.execute("SELECT * FROM dim_data WHERE id = ?", (data_id,)).fetchone()
        assert row["data_completa"] == "2025-01-15"

    def test_mm_aaaa(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        data_id = self._upsert(engine, c, "01/2025")
        assert data_id is not None
        row = c.execute("SELECT * FROM dim_data WHERE id = ?", (data_id,)).fetchone()
        assert row["data_completa"] == "2025-01-01"
        assert row["ano"] == 2025
        assert row["mes"] == 1
        assert row["dia"] == 1

    def test_aaaa_mm_dd(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        data_id = self._upsert(engine, c, "2025-01-15")
        assert data_id is not None
        row = c.execute("SELECT * FROM dim_data WHERE id = ?", (data_id,)).fetchone()
        assert row["data_completa"] == "2025-01-15"

    def test_aaaa_mm(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        data_id = self._upsert(engine, c, "2025-01")
        assert data_id is not None
        row = c.execute("SELECT * FROM dim_data WHERE id = ?", (data_id,)).fetchone()
        assert row["data_completa"] == "2025-01-01"
        assert row["mes"] == 1
        assert row["dia"] == 1

    def test_apenas_ano(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        data_id = self._upsert(engine, c, "2025")
        assert data_id is not None
        row = c.execute("SELECT * FROM dim_data WHERE id = ?", (data_id,)).fetchone()
        assert row["data_completa"] == "2025-01-01"
        assert row["ano"] == 2025

    def test_string_invalida_retorna_none(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        assert engine._upsert_dim_data(c, "invalido") is None
        assert engine._upsert_dim_data(c, "") is None

    def test_trimestre_correto(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        datas_e_trimestres = [
            ("15/01/2025", 1),
            ("15/04/2025", 2),
            ("15/07/2025", 3),
            ("15/10/2025", 4),
        ]
        for data_str, trim_esperado in datas_e_trimestres:
            data_id = engine._upsert_dim_data(c, data_str)
            row = c.execute("SELECT trimestre FROM dim_data WHERE id = ?", (data_id,)).fetchone()
            assert row["trimestre"] == trim_esperado, f"{data_str} -> trimestre {trim_esperado}"


# ─── Testes do _inserir_fact ────────────────────────────────────────────


class TestInserirFact:
    def _seed_dims(self, c):
        """Insere registros minimos nas dimensoes para satisfazer FK."""
        c.execute("""INSERT INTO dim_arquivo (id, nome_arquivo, caminho_completo)
                     VALUES (1, 'test.xlsx', 'db://1')""")
        c.execute("""INSERT INTO dim_data (id, data_completa, ano, mes, dia, trimestre, nome_mes, dia_semana)
                     VALUES (1, '2025-01-15', 2025, 1, 15, 1, 'January', 2)""")
        c.execute("""INSERT INTO dim_coluna (id, schema_hash, nome_coluna_original, nome_coluna_normalizado, tipo_dado)
                     VALUES (1, 'hash', 'col', 'col', 'texto')""")
        c.connection.commit()

    def test_valor_texto(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        self._seed_dims(c)
        engine._inserir_fact(c, 1, 1, 1, "hash", "Sheet1", 1, "texto qualquer")
        row = c.execute("SELECT * FROM fact_dados").fetchone()
        assert row["valor_texto"] == "texto qualquer"
        assert row["valor_numerico"] is None
        assert row["valor_data"] is None

    def test_valor_numerico(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        self._seed_dims(c)
        engine._inserir_fact(c, 1, 1, 1, "hash", "Sheet1", 1, 42.5)
        row = c.execute("SELECT * FROM fact_dados").fetchone()
        assert row["valor_numerico"] == 42.5
        assert row["valor_texto"] is None

    def test_valor_vazio_ignorado(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        self._seed_dims(c)
        engine._inserir_fact(c, 1, 1, 1, "hash", "Sheet1", 1, "")
        engine._inserir_fact(c, 1, 1, 1, "hash", "Sheet1", 1, None)
        rows = c.execute("SELECT COUNT(*) as t FROM fact_dados").fetchone()
        assert rows["t"] == 0

    def test_valor_data_string(self, db):
        engine = TransformEngine(db)
        c = db.conn.cursor()
        self._seed_dims(c)
        engine._inserir_fact(c, 1, 1, 1, "hash", "Sheet1", 1, "15/01/2025")
        row = c.execute("SELECT * FROM fact_dados").fetchone()
        assert row["valor_texto"] == "15/01/2025"
        assert "2025-01-15" in row["valor_data"]


# ─── Testes de integracao do unpivot ────────────────────────────────────


class TestUnpivotStarSchema:
    """Testa o ciclo completo: insercao de raw_data + unpivot."""

    def _seed_raw_data(self, db, schema_hash: str, linhas: list[dict]):
        """Insere dados crus simulando ingestion."""
        c = db.conn.cursor()
        c.execute("""INSERT INTO arquivos (id, nome_arquivo, caminho_completo, status)
                     VALUES (1, 'teste.xlsx', '/fake/teste.xlsx',
                             'ingerido') ON CONFLICT(caminho_completo) DO NOTHING""")
        c.execute(
            """INSERT INTO sheets (id, arquivo_id, nome_sheet, schema_hash, schema_colunas, qtd_linhas, qtd_colunas)
               VALUES (1, 1, 'Sheet1', ?, '[]', 1, 1) ON CONFLICT(arquivo_id, nome_sheet) DO NOTHING""", (schema_hash,))
        db.conn.commit()

        batch = []
        for idx, linha in enumerate(linhas, start=2):
            batch.append((1, 1, idx, schema_hash, json.dumps(linha, ensure_ascii=False)))
        c.executemany("""INSERT INTO raw_data (arquivo_id, sheet_id, linha_id, schema_hash, row_data)
                         VALUES (?, ?, ?, ?, ?)""", batch)
        db.conn.commit()

    def test_unpivot_simples(self, db):
        schema_hash = "test_hash_001"
        linhas = [
            {"Cliente": "Joao", "Regiao": "Sul", "01/2025": 1000, "02/2025": 1500},
            {"Cliente": "Maria", "Regiao": "Norte", "01/2025": 2000, "02/2025": 2500},
        ]
        self._seed_raw_data(db, schema_hash, linhas)

        engine = TransformEngine(db)
        engine.unpivot_para_star_schema(schema_hash)

        fact_count = db.conn.execute("SELECT COUNT(*) as t FROM fact_dados").fetchone()["t"]
        # 2 clientes x (2 fixas + 2 datas) = 8 fact rows
        #   - Joao: Cliente, Regiao, 01/2025, 02/2025 = 4
        #   - Maria: Cliente, Regiao, 01/2025, 02/2025 = 4
        assert fact_count == 8, f"Esperado 8, obtido {fact_count}"

        dim_data_count = db.conn.execute("SELECT COUNT(*) as t FROM dim_data").fetchone()["t"]
        assert dim_data_count == 2  # 01/2025 e 02/2025

    def test_unpivot_com_mesmo_mes_dias_diferentes_nao_colapsa(self, db):
        """Cenario critico: duas colunas de data com dias diferentes no mesmo mes."""
        schema_hash = "test_hash_dias"
        linhas = [
            {"Cliente": "Joao", "15/01/2025": 100, "20/01/2025": 200},
        ]
        self._seed_raw_data(db, schema_hash, linhas)

        engine = TransformEngine(db)
        engine.unpivot_para_star_schema(schema_hash)

        dim_data_count = db.conn.execute("SELECT COUNT(*) as t FROM dim_data").fetchone()["t"]
        # Deve ter 2 datas distintas: 2025-01-15 e 2025-01-20
        assert dim_data_count == 2, f"Esperado 2 datas, obtido {dim_data_count}"

        fact_count = db.conn.execute("SELECT COUNT(*) as t FROM fact_dados").fetchone()["t"]
        # Cliente(fixa) + 15/01 + 20/01 = 3 fact rows
        assert fact_count == 3, f"Esperado 3 facts, obtido {fact_count}"

    def test_unpivot_sem_colunas_fixas_emite_aviso(self, db):
        """Se regex casar colunas demais, deve avisar mas nao crashar."""
        schema_hash = "test_hash_nofixed"
        linhas = [
            {"01/2025": 100, "02/2025": 200},
        ]
        self._seed_raw_data(db, schema_hash, linhas)

        engine = TransformEngine(db)
        engine.unpivot_para_star_schema(schema_hash)

        fact_count = db.conn.execute("SELECT COUNT(*) as t FROM fact_dados").fetchone()["t"]
        assert fact_count == 2  # so as duas datas

    def test_unpivot_dados_repetidos_nao_duplica_dim_data(self, db):
        """Mesma data em linhas diferentes deve gerar apenas um registro em dim_data."""
        schema_hash = "test_hash_dedup"
        linhas = [
            {"Cliente": "Joao", "01/2025": 100},
            {"Cliente": "Maria", "01/2025": 200},
        ]
        self._seed_raw_data(db, schema_hash, linhas)

        engine = TransformEngine(db)
        engine.unpivot_para_star_schema(schema_hash)

        dim_data_count = db.conn.execute("SELECT COUNT(*) as t FROM dim_data").fetchone()["t"]
        assert dim_data_count == 1  # apenas 01/2025

    def test_unpivot_com_cabecalhos_sub_tabela(self, db):
        """Simula sheet com sub-tabelas: linhas de cabecalho repetido com datetime ISO."""
        schema_hash = "test_hash_subtabelas"
        linhas = [
            # Primeira tabela
            {"Regiao": "Norte", "2025-01-10": 1000, "2025-01-11": 2000},
            {"Regiao": "Sul", "2025-01-10": 3000, "2025-01-11": 4000},
            # Cabecalho repetido de sub-tabela (datetime como string ISO)
            {"Regiao": "Regiao", "2025-01-10": "2025-01-10", "2025-01-11": "2025-01-11"},
            # Segunda tabela
            {"Regiao": "Norte", "2025-01-10": 5000, "2025-01-11": 6000},
            {"Regiao": "Sul", "2025-01-10": 7000, "2025-01-11": 8000},
        ]
        self._seed_raw_data(db, schema_hash, linhas)

        engine = TransformEngine(db)
        engine.unpivot_para_star_schema(schema_hash)

        # Deve ter criado dim_data (2 datas)
        dim_data_count = db.conn.execute("SELECT COUNT(*) as t FROM dim_data").fetchone()["t"]
        assert dim_data_count == 2, f"Esperado 2 datas, obtido {dim_data_count}"

        # Deve ter criado fact_dados corretamente
        fact_count = db.conn.execute("SELECT COUNT(*) as t FROM fact_dados").fetchone()["t"]
        # 5 linhas x (1 fixa + 2 datas) = 15 fact rows
        #   Regiao é fixa -> 5 fact rows
        #   2025-01-10 é data -> 5 fact rows
        #   2025-01-11 é data -> 5 fact rows
        assert fact_count == 15, f"Esperado 15 facts, obtido {fact_count}"

        # Verificar que facts com valor_data têm data_id não nulo
        has_null_data = db.conn.execute(
            "SELECT COUNT(*) as t FROM fact_dados WHERE valor_numerico IS NOT NULL AND data_id IS NULL"
        ).fetchone()["t"]
        assert has_null_data == 0, f"Facts com valor numerico mas sem data_id: {has_null_data}"
