from pathlib import Path

import click

from src.core.discovery import DiscoveryEngine
from src.core.ingestion import IngestionEngine
from src.core.transform import TransformEngine
from src.storage.database import Database


@click.group()
@click.option("--db", default="data/pilot.db", help="Caminho do banco SQLite", show_default=True)
@click.option("--migrations", default="migrations", help="Diretorio de migrations", show_default=True)
@click.pass_context
def cli(ctx, db, migrations):
    ctx.ensure_object(dict)
    db_path = Path(ctx.obj.get("workdir", ".")) / db
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(str(db_path))
    database.connect()
    database.run_migrations(migrations)
    ctx.obj["db"] = database


@cli.command()
@click.argument("caminho")
@click.pass_context
def scan(ctx, caminho):
    """Escaneia planilha(s) e detecta schema."""
    db = ctx.obj["db"]
    engine = DiscoveryEngine(db)
    path = Path(caminho)
    if path.is_file():
        engine.scan_sheets(caminho)
    elif path.is_dir():
        engine.scan_recursivo(caminho)
    else:
        click.echo(f"Erro: {caminho} nao encontrado")


@cli.command()
@click.argument("caminho")
@click.pass_context
def ingest(ctx, caminho):
    """Ingere dados crus de planilha(s) para SQLite."""
    db = ctx.obj["db"]
    engine = IngestionEngine(db)
    path = Path(caminho)
    if path.is_file():
        engine.ingestir_arquivo(caminho)
    elif path.is_dir():
        for f in path.rglob("*.xlsx"):
            engine.ingestir_arquivo(str(f))
        for f in path.rglob("*.xls"):
            engine.ingestir_arquivo(str(f))
    else:
        click.echo(f"Erro: {caminho} nao encontrado")


@cli.command()
@click.argument("schema_hash")
@click.option("--regex", default=r"^\d{4}-\d{2}$", help="Regex para detectar colunas-data")
@click.pass_context
def unpivot(ctx, schema_hash, regex):
    """Transforma raw_data em star schema (unpivot)."""
    db = ctx.obj["db"]
    engine = TransformEngine(db)
    engine.unpivot_para_star_schema(schema_hash, regex)


@cli.command()
@click.argument("schema_hash")
@click.option("--coluna-id", default="Cliente", help="Nome da coluna de entidade")
@click.pass_context
def inverter(ctx, schema_hash, coluna_id):
    """Processa planilha invertida (entidades x periodos)."""
    db = ctx.obj["db"]
    engine = TransformEngine(db)
    engine.processar_planilha_invertida(schema_hash, coluna_id)


@cli.command()
@click.pass_context
def status(ctx):
    """Mostra status do banco."""
    db = ctx.obj["db"]
    c = db.conn.cursor()
    click.echo("\n=== Status do Banco ===")
    for tabela in ["arquivos", "sheets", "raw_data", "dim_arquivo", "dim_data", "dim_coluna", "fact_dados"]:
        row = c.execute(f"SELECT COUNT(*) as total FROM {tabela}").fetchone()
        click.echo(f"  {tabela}: {row['total']} registros")
    click.echo("")


@cli.command()
@click.pass_context
def schemas(ctx):
    """Lista todos os schema_hash unicos detectados."""
    db = ctx.obj["db"]
    c = db.conn.cursor()
    rows = c.execute("""
                     SELECT s.schema_hash, a.nome_arquivo, s.nome_sheet, s.qtd_linhas
                     FROM sheets s
                              JOIN arquivos a ON s.arquivo_id = a.id
                     WHERE s.schema_hash IS NOT NULL
                     ORDER BY s.ultimo_hash_modificado DESC
                     """).fetchall()

    click.echo("\n=== Schemas Detectados ===")
    for r in rows:
        click.echo(f"  {r['schema_hash'][:12]}... | {r['nome_arquivo']} | {r['nome_sheet']} ({r['qtd_linhas']} linhas)")
    click.echo("")


@cli.command()
@click.pass_context
def full_pipeline(ctx):
    """Executa scan + ingest + unpivot para todos os schemas (piloto completo)."""
    db = ctx.obj["db"]
    click.echo("\n=== PIPELINE COMPLETO ===")

    discover = DiscoveryEngine(db)
    ingest_eng = IngestionEngine(db)
    transform = TransformEngine(db)

    pendentes = db.conn.execute(
        "SELECT * FROM arquivos WHERE status IN ('pendente', 'scaneado') ORDER BY id"
    ).fetchall()

    if not pendentes:
        click.echo("Nenhum arquivo pendente. Execute 'scan' primeiro ou adicione --db data/pilot.db")
        return

    for arq in pendentes:
        click.echo(f"\n>>> Processando: {arq['nome_arquivo']}")
        if arq["status"] == "pendente":
            discover.scan_sheets(arq["caminho_completo"])
        ingest_eng.ingestir_arquivo(arq["caminho_completo"])

    hashes = db.conn.execute(
        "SELECT DISTINCT schema_hash FROM sheets WHERE schema_hash IS NOT NULL"
    ).fetchall()

    for h in hashes:
        click.echo(f"\n>>> Transformando schema: {h['schema_hash'][:12]}...")
        transform.unpivot_para_star_schema(h["schema_hash"])

    click.echo("\n=== PIPELINE CONCLUIDO ===")
