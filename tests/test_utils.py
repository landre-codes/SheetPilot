"""Testes para src.core.utils — detectar_grupos, iter_rows_lazy, normalizar_cabecalho."""
from datetime import datetime

from src.core.utils import detectar_grupos, normalizar_cabecalho


class TestDetectarGrupos:
    def test_lista_vazia_retorna_vazio(self):
        assert detectar_grupos([]) == []

    def test_sem_linhas_em_branco_retorna_um_grupo(self):
        linhas = [["A", "B"], [1, 2], [3, 4]]
        grupos = detectar_grupos(linhas, min_linhas=2)
        assert len(grupos) == 1
        assert grupos[0] == linhas

    def test_com_linhas_em_branco_separa_grupos(self):
        linhas = [
            ["A", "B"],
            [1, 2],
            [None, None],
            ["C", "D"],
            [3, 4],
        ]
        grupos = detectar_grupos(linhas, min_linhas=2)
        assert len(grupos) == 2
        assert grupos[0] == [["A", "B"], [1, 2]]
        assert grupos[1] == [["C", "D"], [3, 4]]

    def test_grupo_muito_pequeno_e_ignorado(self):
        linhas = [
            ["A"],
            [None, None],
            ["B"],
        ]
        grupos = detectar_grupos(linhas, min_linhas=2)
        assert len(grupos) == 0

    def test_espacos_em_branco_tambem_sao_quebras(self):
        linhas = [
            ["X", "Y"],
            ["", " "],
            ["Z", "W"],
        ]
        grupos = detectar_grupos(linhas, min_linhas=1)
        assert len(grupos) == 2

    def test_min_linhas_personalizado(self):
        linhas = [
            [1],
            [2],
            [3],
            [4],
        ]
        grupos = detectar_grupos(linhas, min_linhas=5)
        assert len(grupos) == 0
        grupos = detectar_grupos(linhas, min_linhas=3)
        assert len(grupos) == 1


class TestNormalizarCabecalho:
    def test_datetime_vira_yyyy_mm_dd(self):
        assert normalizar_cabecalho(datetime(2025, 1, 15)) == "2025-01-15"

    def test_string_permanece_string(self):
        assert normalizar_cabecalho("Cliente") == "Cliente"

    def test_none_vira_vazio(self):
        assert normalizar_cabecalho(None) == ""

    def test_numero_vira_string(self):
        assert normalizar_cabecalho(123) == "123"
