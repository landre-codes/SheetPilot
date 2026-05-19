"""Utility functions shared across ETL pipeline modules."""

from itertools import islice
from typing import Any, Iterator


def detectar_grupos(linhas: list[list], min_linhas: int = 3) -> list[list]:
    """Divide linhas em grupos separados por linhas em branco.
    
    Args:
        linhas: Lista de linhas (cada linha é uma lista de valores).
        min_linhas: Número mínimo de linhas para considerar um grupo válido.
    
    Returns:
        Lista de grupos, onde cada grupo é uma sub-lista de linhas.
    """
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


def iter_rows_lazy(ws, chunk_size: int = 5000) -> Iterator[list[tuple]]:
    """Itera sobre linhas de uma planilha em chunks, evitando
    materialização completa na RAM.
    
    Args:
        ws: Worksheet object (openpyxl) com método iter_rows.
        chunk_size: Número de linhas por chunk.
    
    Yields:
        Listas de até chunk_size linhas.
    """
    it = ws.iter_rows(values_only=True)
    while True:
        chunk = list(islice(it, chunk_size))
        if not chunk:
            break
        yield chunk


def normalizar_cabecalho(valor: Any) -> str:
    """Converte valor de célula para string de cabeçalho preservando data."""
    from datetime import datetime
    s = str(valor or "")
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")
    return s
