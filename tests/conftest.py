import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path para os testes
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from src.storage.database import Database


@pytest.fixture
def db():
    database = Database(":memory:")
    database.connect()
    mig_path = PROJECT_ROOT / "migrations"
    database.run_migrations(str(mig_path))
    return database


@pytest.fixture
def cursor(db):
    return db.conn.cursor()
