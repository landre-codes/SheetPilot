from pathlib import Path

import yaml
from PySide6.QtCore import QThread, Signal

from src.localization import _ as _tr


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
            msg = str(e)
            is_fk = "FOREIGN KEY constraint failed" in msg
            if is_fk:
                msg += _tr(
                    "\n\nThe database appears inconsistent. "
                    "Go to Settings > Maintenance and click 'Analyze' to diagnose, "
                    "or use the 'reset' command in the CLI.")
            self.erro.emit(msg)
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

        try:
            if path.is_file():
                self.log.emit(_tr("[scan] File: {name}").format(name=path.name))
                engine.scan_sheets(self.caminho)
                self.progress.emit(100, _tr("Scan complete"))

            elif path.is_dir():
                ext_order = ["*.xlsx", "*.xlsb", "*.xlsm", "*.csv", "*.parquet"]
                todos = []
                for ext in ext_order:
                    todos.extend(path.rglob(ext))
                total = len(todos)
                self.log.emit(_tr("[scan] {total} files found").format(total=total))

                for i, f in enumerate(todos):
                    if self._cancelled:
                        return
                    engine.scan_sheets(str(f))
                    pct = int((i + 1) / total * 100)
                    self.progress.emit(pct, _tr("Scan: {name}").format(name=f.name))

                self.progress.emit(100, _tr("Scan complete"))
            else:
                raise FileNotFoundError(_tr("Directory/file not found: {path}").format(path=self.caminho))
        finally:
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

        try:
            if path.is_file():
                self.log.emit(_tr("[ingest] {name}").format(name=path.name))
                engine.ingestir_arquivo(self.caminho)
                self.progress.emit(100, _tr("Ingest complete"))

            elif path.is_dir():
                ext_order = ["*.xlsx", "*.xlsb", "*.xlsm", "*.csv", "*.parquet"]
                todos = []
                for ext in ext_order:
                    todos.extend(path.rglob(ext))
                total = len(todos)

                for i, f in enumerate(todos):
                    if self._cancelled:
                        return
                    engine.ingestir_arquivo(str(f))
                    pct = int((i + 1) / total * 100)
                    self.progress.emit(pct, _tr("Ingest: {name}").format(name=f.name))

                self.progress.emit(100, _tr("Ingest complete"))
            else:
                raise FileNotFoundError(_tr("Directory/file not found: {path}").format(path=self.caminho))
        finally:
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

        ext_order = ["*.xlsx", "*.xlsb", "*.xlsm", "*.csv", "*.parquet"]
        todos = []
        for ext in ext_order:
            if path.is_dir():
                todos.extend(path.rglob(ext))
            else:
                todos.append(path)
                break
        total = len(todos)

        self.log.emit(_tr("[both] {total} files found in {path}").format(total=total, path=self.caminho))
        try:
            for i, f in enumerate(todos):
                if self._cancelled:
                    return
                discover.scan_sheets(str(f))
                ingest.ingestir_arquivo(str(f))
                pct = int((i + 1) / total * 100)
                self.progress.emit(pct, _tr("Scan+Ingest: {name}").format(name=f.name))

            self.progress.emit(100, _tr("Scan + Ingest complete"))
        finally:
            db.close()


class TransformWorker(BaseWorker):
    def __init__(self, db_path: str, schema_hash: str = None, parent=None):
        super().__init__(db_path, parent)
        self.schema_hash = schema_hash

    def _load_regex(self) -> str:
        from src.core.transform import COLUNA_DATA_REGEX_DEFAULT
        try:
            cfg_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
            if cfg_path.exists():
                import yaml
                cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                regex = cfg.get("transform", {}).get("coluna_data_regex")
                if regex:
                    return regex
        except Exception:
            pass
        return COLUNA_DATA_REGEX_DEFAULT

    def _exec(self):
        from src.core.transform import TransformEngine
        db = self._get_db()
        engine = TransformEngine(db)
        coluna_data_regex = self._load_regex()

        try:
            count = db.conn.execute(
                "SELECT COUNT(DISTINCT schema_hash) as t FROM sheets WHERE schema_hash IS NOT NULL"
            ).fetchone()["t"]
            total_raw = db.conn.execute("SELECT COUNT(*) as t FROM raw_data").fetchone()["t"]
            total_arquivos = db.conn.execute("SELECT COUNT(*) as t FROM arquivos").fetchone()["t"]
            self.log.emit(_tr("[transform] Files: {f}, Schemas: {s}, Raw: {r}").format(
                f=total_arquivos, s=count, r=total_raw))

            if count == 0:
                self.log.emit(_tr("[transform] No schemas found. Run scan+ingest first."))
                self.log.emit(_tr("[transform] Check that the database contains sheets with a valid schema_hash."))
                return

            if self.schema_hash:
                hid = self.schema_hash
                self.log.emit(_tr("[transform] Schema: {hid}...").format(hid=hid[:12]))
                engine.unpivot_para_star_schema(hid, coluna_data_regex)
                self.progress.emit(100, _tr("Transform complete"))
            else:
                hashes = db.conn.execute(
                    "SELECT DISTINCT schema_hash FROM sheets WHERE schema_hash IS NOT NULL"
                ).fetchall()
                total = len(hashes)
                self.log.emit(_tr("[transform] {total} schema(s) to process").format(total=total))
                for i, h in enumerate(hashes):
                    if self._cancelled:
                        return
                    hid = h["schema_hash"]
                    raw_count = db.conn.execute(
                        "SELECT COUNT(*) as t FROM raw_data WHERE schema_hash = ?", (hid,)
                    ).fetchone()["t"]
                    self.log.emit(_tr("[transform] Schema {i}/{total}: {hid}... ({raw} raw rows)").format(
                        i=i + 1, total=total, hid=hid[:12], raw=raw_count))
                    if raw_count == 0:
                        self.log.emit(_tr("[transform]  -> Skipping (no raw data)"))
                        continue
                    engine.unpivot_para_star_schema(hid, coluna_data_regex)
                    pct = int((i + 1) / total * 100)
                    self.progress.emit(pct, _tr("Transform: schema {i}/{total}").format(i=i + 1, total=total))
                self.progress.emit(100, _tr("Transform complete"))
        finally:
            db.close()


class ExportWorker(BaseWorker):
    """Worker para exportação. Executa em thread separada para não travar a GUI."""

    def __init__(self, db_path: str, destino: str, fmt: str, parent=None):
        super().__init__(db_path, parent)
        self.destino = destino
        self.fmt = fmt

    def _exec(self):
        from collections import defaultdict
        from datetime import datetime
        from pathlib import Path

        from src.core.export import (
            ARQUIVOS_SQL, VALORES_SQL,
            build_corrected, build_raw_table,
            stack_side_by_side, arquivo_id_para_raw,
            export_xlsx, export_xlsb, export_csv, export_parquet,
        )

        dest = Path(self.destino)
        dest.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        db = self._get_db()
        c = db.conn.cursor()
        exported = 0

        try:
            arquivos = c.execute(ARQUIVOS_SQL).fetchall()
            if not arquivos:
                self.log.emit(_tr("[export] No data to export."))
                return

            total = len(arquivos)
            self.log.emit(_tr("[export] {total} file(s) to export").format(total=total))

            for i, arq in enumerate(arquivos):
                if self._cancelled:
                    return
                groups_by_file = []
                arq_id_db = arquivo_id_para_raw(c, arq["arq_id"])

                fact_sheets = c.execute(
                    "SELECT DISTINCT sheet_name FROM fact_dados WHERE arquivo_id = ?",
                    (arq["arq_id"],),
                ).fetchall()

                raw_sheets = []
                if arq_id_db is not None:
                    raw_sheets = c.execute(
                        "SELECT DISTINCT s.nome_sheet FROM raw_data rd "
                        "JOIN sheets s ON rd.sheet_id = s.id "
                        "WHERE rd.arquivo_id = ?",
                        (arq_id_db,),
                    ).fetchall()

                fact_names = {s["sheet_name"] for s in fact_sheets}
                regulares = {}
                sub_agrupadas = defaultdict(list)
                for s in fact_sheets:
                    valores = c.execute(VALORES_SQL, (arq["arq_id"], s["sheet_name"])).fetchall()
                    if not valores:
                        continue
                    col, lin = build_corrected(valores)
                    if "__T" in s["sheet_name"]:
                        base = s["sheet_name"].split("__T")[0]
                        sub_agrupadas[base].append((s["sheet_name"], col, lin))
                    else:
                        regulares[s["sheet_name"]] = (col, lin)

                for nome, (col, lin) in regulares.items():
                    groups_by_file.append(("fact", nome, col, lin))
                for base, subs in sub_agrupadas.items():
                    if len(subs) == 1:
                        _, col, lin = subs[0]
                        groups_by_file.append(("fact", base, col, lin))
                    else:
                        merged = stack_side_by_side(subs)
                        if merged:
                            groups_by_file.append(("fact", base, merged[0], merged[1]))

                for s in raw_sheets:
                    if s["nome_sheet"] in fact_names:
                        continue
                    col, lin = build_raw_table(c, arq_id_db, s["nome_sheet"])
                    if col:
                        groups_by_file.append(("raw", s["nome_sheet"], col, lin))

                if not groups_by_file:
                    continue

                name_base = arq["nome_arquivo"]
                for ext in (".xlsx", ".xlsb", ".xlsm", ".csv", ".parquet"):
                    name_base = name_base.replace(ext, "")
                safe_name = name_base.replace(" ", "_").replace("/", "-")[:40]
                fname = f"{safe_name}_corrigida_{ts}.{self.fmt}"
                fpath = dest / fname
                grupos = [(nome, col, lin) for _, nome, col, lin in groups_by_file]

                try:
                    if self.fmt == "csv":
                        for s_name, scol, srows in grupos:
                            sf = f"{safe_name}_{s_name}_corrigida_{ts}.csv"
                            sp = dest / sf
                            export_csv(sp, scol, srows)
                            self.log.emit(f"  {sf}  ({sp.stat().st_size / 1024:.1f} KB)")
                            exported += 1
                    elif self.fmt == "parquet":
                        for s_name, scol, srows in grupos:
                            sf = f"{safe_name}_{s_name}_corrigida_{ts}.parquet"
                            sp = dest / sf
                            export_parquet(sp, scol, srows)
                            self.log.emit(f"  {sf}  ({sp.stat().st_size / 1024:.1f} KB)")
                            exported += 1
                    elif self.fmt == "xlsb":
                        ok = export_xlsb(fpath, grupos)
                        if not ok:
                            fpath = fpath.with_suffix(".xlsx")
                            export_xlsx(fpath, grupos)
                        sz = fpath.stat().st_size
                        sz_str = f"{sz / 1048576:.1f} MB" if sz > 1048576 else f"{sz / 1024:.1f} KB"
                        self.log.emit(f"  {fname}  ({sz_str}, {len(grupos)} aba(s))")
                        exported += 1
                    else:
                        export_xlsx(fpath, grupos)
                        sz = fpath.stat().st_size
                        sz_str = f"{sz / 1048576:.1f} MB" if sz > 1048576 else f"{sz / 1024:.1f} KB"
                        self.log.emit(f"  {fname}  ({sz_str}, {len(grupos)} aba(s))")
                        exported += 1
                except Exception as e:
                    self.log.emit(f"  {fname}: {e}")
                    continue

                pct = int((i + 1) / total * 100)
                self.progress.emit(pct, _tr("[export] {name}").format(name=fpath.name))

            self.log.emit(_tr("[export] {n} file(s) generated in {dest}").format(
                n=exported, dest=str(dest)))
        finally:
            db.close()


class FullPipelineWorker(BaseWorker):
    # Pesos relativos de cada fase do pipeline (somam 100)
    _WEIGHT_SCAN_INGEST = 66
    _WEIGHT_TRANSFORM = 34

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
        ext_order = ["*.xlsx", "*.xlsb", "*.xlsm", "*.csv", "*.parquet"]
        todos = []
        for ext in ext_order:
            if path.is_dir():
                todos.extend(path.rglob(ext))
            else:
                todos.append(path)
                break

        if not todos:
            raise FileNotFoundError(_tr("No supported files in: {path}").format(path=self.caminho))

        total = len(todos)
        self.log.emit(_tr("[pipeline] Starting pipeline with {total} files in {path}").format(
            total=total, path=self.caminho))

        try:
            for i, f in enumerate(todos):
                if self._cancelled:
                    return
                pct_base = int(i / total * self._WEIGHT_SCAN_INGEST)
                self.progress.emit(pct_base, _tr("Scan+Ingest: {name}").format(name=f.name))
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
                pct = self._WEIGHT_SCAN_INGEST + int((j + 1) / h_total * self._WEIGHT_TRANSFORM)
                self.progress.emit(pct, _tr("Transform: {hid}...").format(hid=hid[:12]))
                transform.unpivot_para_star_schema(hid)

            self.progress.emit(100, _tr("Pipeline complete!"))
        finally:
            db.close()
