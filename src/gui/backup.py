import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

CONFIG_FILENAME = "backup_config.json"


class BackupManager:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.backup_dir = self.db_path.parent / "backups"
        self.config_path = self.db_path.parent / CONFIG_FILENAME
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        return {}

    def _save_config(self, cfg: dict):
        self.config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    def ultimo_backup(self) -> datetime | None:
        cfg = self._load_config()
        val = cfg.get("ultimo_backup")
        if val:
            return datetime.fromisoformat(val)
        return None

    def precisa_backup(self) -> bool:
        ultimo = self.ultimo_backup()
        if ultimo is None:
            return True
        return datetime.now() - ultimo > timedelta(days=7)

    def executar_backup(self) -> str | None:
        if not self.db_path.exists():
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.backup_dir / f"pilot_backup_{ts}.db"
        shutil.copy2(str(self.db_path), str(dest))
        cfg = self._load_config()
        cfg["ultimo_backup"] = datetime.now().isoformat()
        cfg["ultimo_arquivo"] = str(dest)
        self._save_config(cfg)
        return str(dest)

    def listar_backups(self) -> list[dict]:
        backups = []
        for f in sorted(self.backup_dir.glob("*.db"), reverse=True):
            stat = f.stat()
            backups.append({
                "nome": f.name,
                "caminho": str(f),
                "tamanho_kb": round(stat.st_size / 1024, 1),
                "data": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        return backups

    def restaurar_backup(self, caminho_backup: str) -> bool:
        src = Path(caminho_backup)
        if not src.exists():
            return False
        if self.db_path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_backup = self.backup_dir / f"pre_restore_{ts}.db"
            shutil.copy2(str(self.db_path), str(pre_backup))
        shutil.copy2(str(src), str(self.db_path))
        return True


class DatabaseCleanup:
    """Limpeza e otimização do banco de dados."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)

    def diagnostic(self) -> dict:
        """Retorna diagnóstico do que pode ser limpo."""
        from src.storage.database import Database
        db = Database(str(self.db_path))
        db.connect()
        c = db.conn.cursor()
        result = {}

        # raw_data transformados (podem ser apagados)
        row = c.execute("""
                        SELECT COUNT(*) as t
                        FROM raw_data
                        WHERE schema_hash IN (SELECT DISTINCT schema_hash FROM fact_dados)
                        """).fetchone()
        result["raw_orfao"] = row["t"]

        # schema_audit excedente
        row = c.execute("""
                        SELECT COUNT(*) as t
                        FROM schema_audit
                        """).fetchone()
        result["audit_total"] = row["t"]

        # fact_dados duplicados (linhas exatas repetidas)
        row = c.execute("""
                        SELECT COUNT(*) as t
                        FROM (SELECT COUNT(*) as c
                              FROM fact_dados
                              GROUP BY arquivo_id, data_id, coluna_id, schema_hash, sheet_name, linha_origem
                              HAVING c > 1)
                        """).fetchone()
        result["duplicatas"] = row["t"]

        # Tamanho atual
        size_before = self.db_path.stat().st_size if self.db_path.exists() else 0
        result["tamanho_atual_kb"] = round(size_before / 1024, 1)

        db.close()
        return result

    def run_cleanup(self, keep_raw: bool = False) -> dict:
        """Executa limpeza e retorna estatísticas."""
        from src.storage.database import Database
        db = Database(str(self.db_path))
        db.connect()
        c = db.conn.cursor()
        stats = {"removidos_raw": 0, "removidos_audit": 0, "removidos_dup": 0, "backups_excluidos": 0}

        size_before = self.db_path.stat().st_size if self.db_path.exists() else 0

        # 1. Raw data já transformado
        if not keep_raw:
            c.execute("""
                      DELETE
                      FROM raw_data
                      WHERE schema_hash IN (SELECT DISTINCT schema_hash FROM fact_dados)
                      """)
            stats["removidos_raw"] = c.rowcount
            db.conn.commit()

        # 2. Mantém últimas 50 entradas de audit por sheet
        c.execute("""
                  DELETE
                  FROM schema_audit
                  WHERE id IN (SELECT id
                               FROM schema_audit
                               WHERE id NOT IN (SELECT id
                                                FROM (SELECT id,
                                                             ROW_NUMBER() OVER (
                            PARTITION BY sheet_id ORDER BY detectado_em DESC
                        ) as rn
                                                      FROM schema_audit)
                                                WHERE rn <= 50))
                  """)
        stats["removidos_audit"] = c.rowcount
        db.conn.commit()

        # 3. Remove duplicatas de fact_dados
        c.execute("""
                  DELETE
                  FROM fact_dados
                  WHERE id NOT IN (SELECT MIN(id)
                                   FROM fact_dados
                                   GROUP BY arquivo_id, data_id, coluna_id, schema_hash, sheet_name, linha_origem)
                  """)
        stats["removidos_dup"] = c.rowcount
        db.conn.commit()

        db.close()

        # 4. VACUUM (reclaim space)
        db2 = Database(str(self.db_path))
        db2.connect()
        db2.conn.execute("VACUUM")
        db2.close()

        size_after = self.db_path.stat().st_size if self.db_path.exists() else 0
        stats["tamanho_antes_kb"] = round(size_before / 1024, 1)
        stats["tamanho_depois_kb"] = round(size_after / 1024, 1)
        stats["economia_kb"] = round((size_before - size_after) / 1024, 1)

        # 5. Limpa backups antigos (> 30 dias, mantém o mais recente)
        backup_dir = self.db_path.parent / "backups"
        if backup_dir.exists():
            backups = sorted(backup_dir.glob("*.db"), key=lambda f: f.stat().st_mtime, reverse=True)
            cutoff = datetime.now() - timedelta(days=30)
            kept_one = False
            for f in backups:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    if not kept_one:
                        kept_one = True  # keep the most recent even if old
                        continue
                    f.unlink()
                    stats["backups_excluidos"] += 1

        return stats
