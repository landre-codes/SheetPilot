#!/usr/bin/env python3
"""
Planilha BI Pilot — Entrypoint principal
Uso:
  python main.py --cli scan ./data/sample
  python main.py --cli full-pipeline
  python main.py --gui
  python main.py            (abre GUI com banco padrao em ~/planilha_bi_db/)
"""
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Planilha BI Pilot")
    parser.add_argument("--cli", action="store_true", help="Modo CLI (headless)")
    parser.add_argument("--gui", action="store_true", help="Modo GUI (interface grafica)")
    parser.add_argument("--db", default=None, help="Caminho do banco SQLite (opcional na GUI)")
    parser.add_argument("--migrations", default=None, help="Diretorio de migrations")
    args, unknown = parser.parse_known_args()

    base_dir = Path(__file__).parent

    if args.cli:
        from src.storage.database import Database
        db_path = Path(args.db or base_dir / "data/pilot.db")
        mig_path = Path(args.migrations or base_dir / "migrations")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        database = Database(str(db_path))
        database.connect()
        database.run_migrations(str(mig_path))

        from src.cli.commands import cli as click_cli
        sys.argv = [sys.argv[0]] + unknown
        click_cli(auto_envvar_prefix="PLANILHA_BI", obj={
            "db": database,
            "workdir": str(base_dir)
        })
    else:
        from src.gui.main_window import start_gui
        start_gui()


if __name__ == "__main__":
    main()
