from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ArquivoMetadata(BaseModel):
    id: Optional[int] = None
    nome_arquivo: str
    caminho_completo: str
    ultima_modificacao: Optional[datetime] = None
    tamanho_bytes: Optional[int] = None
    status: str = "pendente"


class SheetMetadata(BaseModel):
    id: Optional[int] = None
    arquivo_id: int
    nome_sheet: str
    schema_hash: Optional[str] = None
    schema_colunas: Optional[str] = None
    schema_tipos: Optional[str] = None
    qtd_linhas: Optional[int] = None
    qtd_colunas: Optional[int] = None


class MapeamentoConfig(BaseModel):
    schema_hash: str
    descricao: str = ""
    coluna_cliente: Optional[str] = None
    coluna_data_regex: str = r"^(?:\d{2}[/-]\d{2}[/-]\d{4}|\d{2}[/-]\d{4}|\d{4}[/-]\d{2}(?:[/-]\d{2})?|\d{4})$"
    colunas_ignorar: list[str] = Field(default_factory=list)
    tabela_destino: str = "generic"
    mapeamento_extra: dict[str, str] = Field(default_factory=dict)
