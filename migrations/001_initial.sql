-- Migration 001: Schema inicial do piloto
-- Tabelas de metadados, raw ingestion e star schema

BEGIN
TRANSACTION;

-- ============================================================
-- METADATA LAYER
-- ============================================================

CREATE TABLE IF NOT EXISTS _migrations
(
    id
    INTEGER
    PRIMARY
    KEY
    AUTOINCREMENT,
    filename
    TEXT
    NOT
    NULL
    UNIQUE,
    applied_at
    DATETIME
    DEFAULT
    CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS arquivos
(
    id
    INTEGER
    PRIMARY
    KEY
    AUTOINCREMENT,
    nome_arquivo
    TEXT
    NOT
    NULL,
    caminho_completo
    TEXT
    NOT
    NULL
    UNIQUE,
    ultima_modificacao
    DATETIME,
    tamanho_bytes
    INTEGER,
    status
    TEXT
    DEFAULT
    'pendente', -- pendente, scaneado, ingerido, erro
    created_at
    DATETIME
    DEFAULT
    CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sheets
(
    id
    INTEGER
    PRIMARY
    KEY
    AUTOINCREMENT,
    arquivo_id
    INTEGER
    NOT
    NULL
    REFERENCES
    arquivos
(
    id
) ON DELETE CASCADE,
    nome_sheet TEXT NOT NULL,
    schema_hash TEXT, -- MD5 do cabeçalho (nomes de coluna)
    schema_colunas TEXT, -- JSON array com nomes das colunas
    schema_tipos TEXT, -- JSON array com tipos inferidos
    qtd_linhas INTEGER,
    qtd_colunas INTEGER,
    ultimo_hash_modificado DATETIME,
    UNIQUE
(
    arquivo_id,
    nome_sheet
)
    );

CREATE TABLE IF NOT EXISTS schema_audit
(
    id
    INTEGER
    PRIMARY
    KEY
    AUTOINCREMENT,
    sheet_id
    INTEGER
    NOT
    NULL
    REFERENCES
    sheets
(
    id
) ON DELETE CASCADE,
    schema_hash_anterior TEXT,
    schema_hash_novo TEXT NOT NULL,
    colunas_adicionadas TEXT, -- JSON array
    colunas_removidas TEXT, -- JSON array
    detectado_em DATETIME DEFAULT CURRENT_TIMESTAMP
    );

-- ============================================================
-- RAW INGESTION LAYER (EAV-style with JSON)
-- ============================================================

CREATE TABLE IF NOT EXISTS raw_data
(
    id
    INTEGER
    PRIMARY
    KEY
    AUTOINCREMENT,
    arquivo_id
    INTEGER
    NOT
    NULL
    REFERENCES
    arquivos
(
    id
) ON DELETE CASCADE,
    sheet_id INTEGER NOT NULL REFERENCES sheets
(
    id
)
  ON DELETE CASCADE,
    linha_id INTEGER NOT NULL, -- número da linha original
    schema_hash TEXT NOT NULL, -- qual versão do schema estava vigente
    row_data TEXT NOT NULL, -- JSON: {"Coluna": "valor", ...}
    ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

CREATE INDEX idx_raw_data_sheet ON raw_data (sheet_id);
CREATE INDEX idx_raw_data_hash ON raw_data (schema_hash);

-- ============================================================
-- STAR SCHEMA LAYER (output limpo)
-- ============================================================

CREATE TABLE IF NOT EXISTS dim_arquivo
(
    id
    INTEGER
    PRIMARY
    KEY
    AUTOINCREMENT,
    nome_arquivo
    TEXT
    NOT
    NULL,
    caminho_completo
    TEXT
    NOT
    NULL
    UNIQUE
);

CREATE TABLE IF NOT EXISTS dim_data
(
    id
    INTEGER
    PRIMARY
    KEY
    AUTOINCREMENT,
    data_completa
    DATE
    NOT
    NULL
    UNIQUE,
    ano
    INTEGER
    NOT
    NULL,
    mes
    INTEGER
    NOT
    NULL,
    dia
    INTEGER
    NOT
    NULL,
    trimestre
    INTEGER
    NOT
    NULL,
    nome_mes
    TEXT
    NOT
    NULL,
    dia_semana
    INTEGER
);

CREATE TABLE IF NOT EXISTS dim_coluna
(
    id
    INTEGER
    PRIMARY
    KEY
    AUTOINCREMENT,
    schema_hash
    TEXT
    NOT
    NULL,
    nome_coluna_original
    TEXT
    NOT
    NULL,
    nome_coluna_normalizado
    TEXT
    NOT
    NULL, -- sem acentos, sem espaços
    tipo_dado
    TEXT,
    UNIQUE
(
    schema_hash,
    nome_coluna_original
)
    );

CREATE TABLE IF NOT EXISTS fact_dados
(
    id
    INTEGER
    PRIMARY
    KEY
    AUTOINCREMENT,
    arquivo_id
    INTEGER
    REFERENCES
    dim_arquivo
(
    id
),
    data_id INTEGER REFERENCES dim_data
(
    id
),
    coluna_id INTEGER REFERENCES dim_coluna
(
    id
),
    schema_hash TEXT,
    sheet_name TEXT,
    linha_origem INTEGER,
    valor_texto TEXT,
    valor_numerico REAL,
    valor_data DATETIME,
    ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

CREATE INDEX idx_fact_data ON fact_dados (data_id);
CREATE INDEX idx_fact_arquivo ON fact_dados (arquivo_id);
CREATE INDEX idx_fact_hash ON fact_dados (schema_hash);

-- ============================================================
-- VIEW PARA UNPIVOT GENÉRICO
-- ============================================================

CREATE VIEW IF NOT EXISTS vw_dados_unpivot AS
SELECT f.id,
       da.nome_arquivo,
       f.sheet_name,
       f.linha_origem,
       dc.nome_coluna_original,
       dc.nome_coluna_normalizado,
       f.valor_texto,
       f.valor_numerico,
       f.valor_data,
       dd.data_completa,
       dd.ano,
       dd.mes
FROM fact_dados f
         LEFT JOIN dim_arquivo da ON f.arquivo_id = da.id
         LEFT JOIN dim_data dd ON f.data_id = dd.id
         LEFT JOIN dim_coluna dc ON f.coluna_id = dc.id;

COMMIT;
