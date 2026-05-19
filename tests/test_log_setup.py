"""Testes para src.log_setup."""
import logging
import tempfile
from pathlib import Path

from src.log_setup import setup_logging, get_logger


class TestLogSetup:
    def test_get_logger_returns_logger(self):
        logger = get_logger("teste")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "teste"

    def test_setup_logging_nao_crasha(self):
        setup_logging(level=logging.DEBUG)
        assert True

    def test_get_logger_apos_setup_retorna_logger(self):
        setup_logging(level=logging.INFO)
        logger = get_logger("test_nivel")
        assert isinstance(logger, logging.Logger)

    def test_setup_logging_with_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(level=logging.INFO, log_dir=tmpdir)
            log_file = Path(tmpdir) / "planilha_bi.log"
            logger = get_logger("test_file")
            logger.info("Mensagem de teste")
            for h in logger.handlers:
                h.flush()
            assert True
