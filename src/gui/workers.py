from pathlib import Path
import yaml

from PySide6.QtCore import QThread, Signal


def _config_discovery(engine):
    """Aplica configuração de detecção de tabelas ao DiscoveryEngine."""
    try:
        cfg_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            scan_cfg = cfg.get("scan", {})
            engine.config(
                detectar_tabelas=scan_cfg.get("detectar_tabelas", False),
                min_linhas=scan_cfg.get("min_linhas_tabela", 3)
            )
    except Exception:
        pass


class BaseWorker(QThread):
    log = Signal(str)
    progress = Signal(int, str)
    finished = Signal(bool)
    erro = Signal(str)

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _get_db(self):
        from src.storage.database import Database
        db = Database(self.db_path)
        db.connect()
        return db

    def run(self):
        try:
            self._exec()
            if not self._cancelled:
                self.finished.emit(True)
        except Exception as e:
            self.erro.emit(str(e))
            self.finished.emit(False)


class ScanWorker(BaseWorker):
    def __init__(self, db_path: str, caminho: str, parent=None):
        super().__init__(db_path, parent)
        self.caminho = caminho

    def _exec(self):
        from src.core.discovery import DiscoveryEngine
        db = self._get_db()
        engine = DiscoveryEngine(db)
        _config_discovery(engine)
        path = Path(self.caminho)

        if path.is_file():
            self.log.emit(f"[scan] Arquivo: {path.name}")
            engine.scan_sheets(self.caminho)
            self.progress.emit(100, "Scan concluido")

        elif path.is_dir():
            ext_order = ["*.xlsx", "*.xlsb", "*.csv", "*.parquet"]
            todos = []
            for ext in ext_order:
                todos.extend(path.rglob(ext))
            total = len(todos)
            self.log.emit(f"[scan] {total} arquivos encontrados")

            for i, f in enumerate(todos):
                if self._cancelled:
                    return
                engine.scan_sheets(str(f))
                pct = int((i + 1) / total * 100)
                self.progress.emit(pct, f"Scan: {f.name}")

            self.progress.emit(100, "Scan concluido")
        else:
            raise FileNotFoundError(f"Diretorio/arquivo nao encontrado: {self.caminho}")

        db.close()


class IngestWorker(BaseWorker):
    def __init__(self, db_path: str, caminho: str, parent=None):
        super().__init__(db_path, parent)
        self.caminho = caminho

    def _exec(self):
        from src.core.ingestion import IngestionEngine
        db = self._get_db()
        engine = IngestionEngine(db)
        path = Path(self.caminho)

        if path.is_file():
            self.log.emit(f"[ingest] {path.name}")
            engine.ingestir_arquivo(self.caminho)
            self.progress.emit(100, "Ingestao concluida")

        elif path.is_dir():
            ext_order = ["*.xlsx", "*.xlsb", "*.csv", "*.parquet"]
            todos = []
            for ext in ext_order:
                todos.extend(path.rglob(ext))
            total = len(todos)

            for i, f in enumerate(todos):
                if self._cancelled:
                    return
                engine.ingestir_arquivo(str(f))
                pct = int((i + 1) / total * 100)
                self.progress.emit(pct, f"Ingest: {f.name}")

            self.progress.emit(100, "Ingestao concluida")
        else:
            raise FileNotFoundError(f"Diretorio/arquivo nao encontrado: {self.caminho}")

        db.close()


class BothWorker(BaseWorker):
    def __init__(self, db_path: str, caminho: str, parent=None):
        super().__init__(db_path, parent)
        self.caminho = caminho

    def _exec(self):
        from src.core.discovery import DiscoveryEngine
        from src.core.ingestion import IngestionEngine
        db = self._get_db()
        discover = DiscoveryEngine(db)
        _config_discovery(discover)
        ingest = IngestionEngine(db)
        path = Path(self.caminho)

        ext_order = ["*.xlsx", "*.xlsb", "*.csv", "*.parquet"]
        todos = []
        for ext in ext_order:
            if path.is_dir():
                todos.extend(path.rglob(ext))
            else:
                todos.append(path)
                break
        total = len(todos)

        self.log.emit(f"[both] {total} arquivos encontrados em {self.caminho}")
        for i, f in enumerate(todos):
            if self._cancelled:
                return
            discover.scan_sheets(str(f))
            ingest.ingestir_arquivo(str(f))
            pct = int((i + 1) / total * 100)
            self.progress.emit(pct, f"Scan+Ingest: {f.name}")

        self.progress.emit(100, "Scan + Ingest concluido")
        db.close()


class TransformWorker(BaseWorker):
    def __init__(self, db_path: str, schema_hash: str = None, parent=None):
        super().__init__(db_path, parent)
        self.schema_hash = schema_hash

    def _exec(self):
        from src.core.transform import TransformEngine
        db = self._get_db()
        engine = TransformEngine(db)

        if self.schema_hash:
            hid = self.schema_hash
            self.log.emit(f"[transform] Schema: {hid[:12]}...")
            engine.unpivot_para_star_schema(hid)
            self.progress.emit(100, "Transform concluido")
        else:
            hashes = db.conn.execute(
                "SELECT DISTINCT schema_hash FROM sheets WHERE schema_hash IS NOT NULL"
            ).fetchall()
            total = len(hashes)
            for i, h in enumerate(hashes):
                if self._cancelled:
                    return
                hid = h["schema_hash"]
                self.log.emit(f"[transform] Schema {i + 1}/{total}: {hid[:12]}...")
                engine.unpivot_para_star_schema(hid)
                pct = int((i + 1) / total * 100)
                self.progress.emit(pct, f"Transform: schema {i + 1}/{total}")
            self.progress.emit(100, "Transform concluido")

        db.close()


class FullPipelineWorker(BaseWorker):
    def __init__(self, db_path: str, caminho: str, parent=None):
        super().__init__(db_path, parent)
        self.caminho = caminho

    def _exec(self):
        from src.core.discovery import DiscoveryEngine
        from src.core.ingestion import IngestionEngine
        from src.core.transform import TransformEngine
        db = self._get_db()
        discover = DiscoveryEngine(db)
        _config_discovery(discover)
        ingest = IngestionEngine(db)
        transform = TransformEngine(db)

        path = Path(self.caminho)
        ext_order = ["*.xlsx", "*.xlsb", "*.csv", "*.parquet"]
        todos = []
        for ext in ext_order:
            if path.is_dir():
                todos.extend(path.rglob(ext))
            else:
                todos.append(path)
                break

        if not todos:
            raise FileNotFoundError(f"Nenhum arquivo suportado em: {self.caminho}")

        total = len(todos)
        self.log.emit(f"[pipeline] Iniciando pipeline com {total} arquivos em {self.caminho}")

        for i, f in enumerate(todos):
            if self._cancelled:
                return
            pct_base = int(i / total * 66)
            self.progress.emit(pct_base, f"Scan+Ingest: {f.name}")
            discover.scan_sheets(str(f))
            ingest.ingestir_arquivo(str(f))

        hashes = db.conn.execute(
            "SELECT DISTINCT schema_hash FROM sheets WHERE schema_hash IS NOT NULL"
        ).fetchall()
        h_total = len(hashes)
        for j, h in enumerate(hashes):
            if self._cancelled:
                return
            hid = h["schema_hash"]
            pct = 66 + int((j + 1) / h_total * 34)
            self.progress.emit(pct, f"Transform: {hid[:12]}...")
            transform.unpivot_para_star_schema(hid)

        self.progress.emit(100, "Pipeline concluido!")
        db.close()
