"""Testes para src.core.discovery — especialmente _normalizar_cabecalho."""
from datetime import datetime

from src.core.utils import normalizar_cabecalho as _normalizar_cabecalho


class TestNormalizarCabecalho:
    def test_datetime_vira_yyyy_mm_dd(self):
        dt = datetime(2025, 1, 15)
        assert _normalizar_cabecalho(dt) == "2025-01-15"

    def test_datetime_primeiro_dia_mes(self):
        dt = datetime(2025, 1, 1)
        assert _normalizar_cabecalho(dt) == "2025-01-01"

    def test_string_permanece_string(self):
        assert _normalizar_cabecalho("Cliente") == "Cliente"

    def test_none_vira_vazio(self):
        assert _normalizar_cabecalho(None) == ""

    def test_numero_vira_string(self):
        assert _normalizar_cabecalho(123) == "123"

    def test_datas_diferentes_no_mesmo_mes_nao_colapsam(self):
        """Esse é o bug crítico que foi corrigido:
        antes retornava '2025-01' para ambos, agora retorna datas distintas."""
        dt1 = datetime(2025, 1, 15)
        dt2 = datetime(2025, 1, 20)
        assert _normalizar_cabecalho(dt1) != _normalizar_cabecalho(dt2)
        assert _normalizar_cabecalho(dt1) == "2025-01-15"
        assert _normalizar_cabecalho(dt2) == "2025-01-20"
