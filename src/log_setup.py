import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(level: int = logging.INFO, log_dir: str | None = None):
    handlers: list[logging.Handler] = []

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(
        "[%(levelname)s] %(name)s: %(message)s"
    ))
    handlers.append(console)

    if log_dir:
        p = Path(log_dir)
        p.mkdir(parents=True, exist_ok=True)
        file_h = RotatingFileHandler(
            p / "planilha_bi.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_h.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        handlers.append(file_h)

    logging.basicConfig(level=level, handlers=handlers)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
