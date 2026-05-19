# SheetPilot

**Smart spreadsheet correction & normalization**

SheetPilot detects and corrects inverted spreadsheets where dates are placed as columns instead of rows. It unpivots
them into a clean star-schema format, preserves multiple tables within the same sheet, and exports ready-to-use
corrected files.

## Features

- **Inverted table detection** — Automatically finds spreadsheets with dates as columns and normalizes them
- **Multi-table support** — Detects multiple tables stacked vertically in the same sheet, separated by blank rows
- **Side-by-side merge** — Corrected tables are placed side by side with visual separators, preserving the original
  layout
- **Normal table pass-through** — Already-normalized tables are kept unchanged
- **Multiple export formats** — xlsx (formatted), xlsb, csv, parquet
- **Star schema storage** — Data is stored in a normalized star schema (SQLite) for flexible querying
- **Session history** — Tracks all operations (import, transform, export, backup) across sessions
- **Weekly auto-backup** — Database backups with automatic cleanup of old backups
- **Automatic cleanup** — Removes orphan raw data, duplicates, and old backups
- **Drag & drop** — Drag folders directly onto the import page
- **Recent folders** — Quick access to previously imported folders
- **Multi-language** — Interface in Portuguese (default) and English
- **Dark theme** — Premium dark interface with custom title bar
- **Frameless window** — Custom title bar with drag, minimize, maximize, and close

## Installation

### Requirements

- Python 3.10+
- Windows (for xlsb export via Excel COM)

### Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/SheetPilot.git
cd SheetPilot

# Install dependencies
pip install -r requirements.txt

# Run
python main.py --gui
```

### CLI Mode

```bash
# Full pipeline (scan + ingest + transform)
python main.py --cli full-pipeline

# Scan only
python main.py --cli scan ./data/sample

# Status
python main.py --cli status
```

## Usage

1. **Import** — Select a folder with Excel files (`.xlsx`, `.xlsb`, `.csv`, `.parquet`)
2. **Transform** — Convert inverted tables (dates as columns) to normalized format
3. **Export** — Generate corrected spreadsheets in your preferred format

### Multi-table Detection

Enable in `config/settings.yaml`:

```yaml
scan:
  detectar_tabelas: true
  min_linhas_tabela: 3
```

This detects tables separated by blank rows within the same sheet and processes them independently.

## Project Structure

```
SheetPilot/
├── main.py                    # Entry point (GUI or CLI)
├── config/settings.yaml       # Global configuration
├── lang/                      # Translation files (.json)
│   ├── pt_BR.json
│   └── en_US.json
├── migrations/                # SQLite schema migrations
├── src/
│   ├── core/                  # Pipeline engine
│   │   ├── discovery.py       # Schema scanner
│   │   ├── ingestion.py       # Raw data reader
│   │   ├── transform.py       # Unpivot engine
│   │   └── models.py          # Data models
│   ├── storage/               # Database layer
│   │   ├── database.py        # SQLite connection + migrations
│   │   ├── metadata_repo.py   # Metadata CRUD
│   │   └── raw_repo.py        # Raw data CRUD
│   ├── gui/                   # Desktop interface
│   │   ├── main_window.py     # Main window (frameless + title bar)
│   │   ├── pages.py           # All page widgets
│   │   ├── workers.py         # Background QThread workers
│   │   ├── backup.py          # Backup manager + database cleanup
│   │   └── widgets/
│   │       ├── sidebar.py     # Animated sidebar
│   │       └── titlebar.py    # Custom title bar
│   ├── cli/commands.py        # Click CLI
│   └── localization.py        # i18n support
├── scripts/
│   ├── gerar_sample.py        # Sample data generator
│   └── run_pipeline.bat       # Windows Task Scheduler script
└── data/sample/               # Sample spreadsheets
```

## Tech Stack

- **Python 3.14** — Core language
- **PySide6** — Desktop GUI framework
- **qt-material** — Material Design dark theme
- **qtawesome** — Font Awesome icons
- **openpyxl** — Excel read/write
- **SQLite** — Local database (WAL mode)
- **Click** — CLI interface
- **PyArrow** — Parquet export

## License

MIT License — see [LICENSE](LICENSE).

Copyright (c) 2026 SheetPilot.
