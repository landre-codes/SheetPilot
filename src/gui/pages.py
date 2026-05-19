import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, QSize, QStringListModel
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QTextEdit, QGroupBox,
    QProgressBar, QMessageBox, QListWidget, QListWidgetItem,
    QFrame, QComboBox, QScrollArea, QCompleter,
)

from src.localization import _, on_language_change
from src.log_setup import get_logger

logger = get_logger(__name__)

from src.core.export import (
    ARQUIVOS_SQL, VALORES_SQL,
    build_corrected, build_raw_table,
    stack_side_by_side, arquivo_id_para_raw,
    export_xlsx, export_xlsb, export_csv, export_parquet,
)
from src.gui.workers import (
    BothWorker,
    ExportWorker,
    TransformWorker, )
from src.gui.backup import BackupManager, DatabaseCleanup

# ── Histórico de operações da sessão ─────────
_LOG_FILE = Path.home() / "sheetpilot_db" / "historico.json"


@dataclass
class Operacao:
    tipo: str  # "importar", "ajustar", "exportar", "backup", "limpeza"
    descricao: str
    status: str  # "ok", "erro"
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")


_historico_sessao: list[Operacao] = []


def _carregar_historico() -> list[Operacao]:
    try:
        if _LOG_FILE.exists():
            data = json.loads(_LOG_FILE.read_text(encoding="utf-8"))
            return [Operacao(**o) for o in data[-50:]]  # últimas 50
    except Exception:
        pass
    return []


def _salvar_historico():
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOG_FILE.write_text(
            json.dumps([asdict(o) for o in _historico_sessao[-100:]], ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass


def registrar_operacao(tipo: str, descricao: str, status: str = "ok"):
    op = Operacao(tipo, descricao, status)
    _historico_sessao.append(op)
    _salvar_historico()


# ── Styled button ────────────────────────────
def _mkbtn(text: str, icon_name: str = None, color: str = "#2E7D32",
           hover: str = "#388E3C") -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setMinimumHeight(42)
    if icon_name:
        btn.setIcon(qta.icon(icon_name, color="white"))
        btn.setIconSize(QSize(18, 18))
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {color}; color: white; border: none;
            border-radius: 8px; padding: 8px 20px; font-size: 13px;
            font-weight: bold;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:disabled {{ background-color: #37474F; color: #78909C; }}
    """)
    return btn


# ── Page base ────────────────────────────────
class BasePage(QWidget):
    def __init__(self, db, page_title="", parent=None):
        super().__init__(parent)
        self.db = db
        self.page_title = page_title
        self._worker = None
        self._build_ui()
        on_language_change(lambda: self.retranslate_ui())

    def _build_ui(self):
        raise NotImplementedError

    def retranslate_ui(self):
        """Atualiza textos após mudança de idioma. Sobrescrever nas subclasses."""
        pass

    def _log_area(self):
        log = QTextEdit()
        log.setReadOnly(True)
        log.setFont(QFont("Consolas", 10))
        log.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117; color: #c9d1d9;
                border: 1px solid #30363d; border-radius: 6px; padding: 8px;
            }
        """)
        return log

    def _path_input(self, placeholder="", btn_icon="fa5s.folder-open", btn_text=""):
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet("""
            QLineEdit {
                padding: 8px 12px; border: 1px solid #30363d;
                border-radius: 6px; background-color: #0d1117;
                color: #c9d1d9; font-size: 13px;
            }
        """)
        btn = QPushButton()
        if btn_icon:
            btn.setIcon(qta.icon(btn_icon, color="white"))
            btn.setIconSize(QSize(16, 16))
        if btn_text:
            btn.setText(btn_text)
        btn.setFixedWidth(120)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #1976D2; color: white; border: none;
                border-radius: 6px; padding: 8px 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1565C0; }
            QPushButton:disabled { background-color: #37474F; color: #78909C; }
        """)
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        return row, edit, btn

    def _progress(self):
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(True)
        bar.setFixedHeight(22)
        bar.setStyleSheet("""
            QProgressBar {
                background-color: #0d1117; border: 1px solid #30363d;
                border-radius: 6px; text-align: center; color: white;
                font-size: 11px;
            }
            QProgressBar::chunk { background-color: #2E7D32; border-radius: 5px; }
        """)
        return bar

    def _db_path(self):
        return self.db.db_path

    def _exec_worker(self, worker):
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, _("Warning"), _("Operation in progress."))
            return
        self._worker = worker
        self._worker.log.connect(self._on_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.erro.connect(self._on_error)
        self._worker.start()

    def _on_log(self, text):
        pass

    def _on_progress(self, value, text):
        pass

    def _on_finished(self, ok):
        pass

    def _on_error(self, msg):
        QMessageBox.critical(self, _("Error"), msg)


# ─────────────────────────────────────────────
#  Dashboard (simplificado)
# ─────────────────────────────────────────────
_ICONES_TIPO = {
    "importar": ("fa5s.file-import", "#42A5F5"),
    "ajustar": ("fa5s.sync-alt", "#AB47BC"),
    "exportar": ("fa5s.file-export", "#66BB6A"),
    "backup": ("fa5s.archive", "#FFA726"),
    "limpeza": ("fa5s.broom", "#EF5350"),
}


class DashboardPage(BasePage):
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        # Welcome
        welcome = QLabel(_("SheetPilot"))
        welcome.setStyleSheet("""
            font-family: 'Montserrat', 'Segoe UI', sans-serif;
            font-size: 28px; font-weight: 600; letter-spacing: 2px;
            color: #E0F7FA;
        """)
        layout.addWidget(welcome)

        sub = QLabel(_("Smart spreadsheet correction & normalization"))
        sub.setStyleSheet("color: #80DEEA; font-size: 13px; letter-spacing: 0.5px; margin-bottom: 8px;")
        layout.addWidget(sub)

        # Next step indicator
        self.next_step = QFrame()
        self.next_step.setStyleSheet("""
            QFrame {
                background-color: #0d2137; border: 1px solid #1a3a5c;
                border-radius: 8px; border-left: 4px solid #42A5F5;
                padding: 10px 16px; margin-bottom: 8px;
            }
        """)
        nsl = QHBoxLayout(self.next_step)
        nsl.setContentsMargins(12, 8, 12, 8)
        self.ns_icon = QLabel()
        self.ns_icon.setPixmap(qta.icon("fa5s.lightbulb", color="#FFD54F").pixmap(18, 18))
        nsl.addWidget(self.ns_icon)
        self.ns_label = QLabel(_("Loading sheets..."))
        self.ns_label.setStyleSheet("color: #B0BEC5; font-size: 12px; background: transparent;")
        nsl.addWidget(self.ns_label, stretch=1)
        self.ns_btn = QPushButton(_("Go"))
        self.ns_btn.setFixedSize(50, 26)
        self.ns_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ns_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976D2; color: white; border: none;
                border-radius: 4px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1565C0; }
        """)
        self._ns_pagina = None
        self.ns_btn.clicked.connect(self._ir_para_ns)
        nsl.addWidget(self.ns_btn)
        layout.addWidget(self.next_step)

        # Quick action cards
        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        tip_import = _("Import spreadsheets")
        tip_ajustar = _("Adjust inverted tables")
        tip_export = _("Export corrected spreadsheets")
        for texto, icone, cor, dica, pagina in [
            (_("Import"), "fa5s.file-import", "#1976D2", tip_import, "importar"),
            (_("Adjust"), "fa5s.sync-alt", "#7B1FA2", tip_ajustar, "transformar"),
            (_("Export"), "fa5s.file-export", "#388E3C", tip_export, "exportar"),
        ]:
            card = QFrame()
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: #1a1a2e; border: 1px solid #2a2a4e;
                    border-radius: 12px; border-top: 3px solid {cor};
                    padding: 16px;
                }}
                QFrame:hover {{
                    background-color: #222248; border-color: {cor};
                }}
            """)
            cl = QVBoxLayout(card)
            cl.setAlignment(Qt.AlignCenter)
            cl.setSpacing(4)
            ic = QLabel()
            ic.setPixmap(qta.icon(icone, color=cor).pixmap(32, 32))
            ic.setAlignment(Qt.AlignCenter)
            cl.addWidget(ic)
            lb = QLabel(texto)
            lb.setAlignment(Qt.AlignCenter)
            lb.setStyleSheet(f"color: #E0E0E0; font-size: 13px; font-weight: bold; margin-top: 4px;")
            cl.addWidget(lb)
            card.mousePressEvent = lambda e, p=pagina: self._ir_para(p)
            card.setToolTip(dica)
            acoes.addWidget(card)

        layout.addLayout(acoes)

        # Status cards
        self.stat_labels = {}
        status_grid = QHBoxLayout()
        status_grid.setSpacing(10)
        for chave, rotulo, icone, cor in [
            ("arquivos", _("Files"), "fa5s.file-excel", "#2196F3"),
            ("sheets", _("Sheets"), "fa5s.table", "#4CAF50"),
            ("raw_data", _("Lines read"), "fa5s.database", "#FF9800"),
        ]:
            f = QFrame()
            f.setStyleSheet(f"""
                QFrame {{
                    background-color: #1a1a2e; border: 1px solid #2a2a4e;
                    border-radius: 10px; border-left: 3px solid {cor};
                    padding: 12px;
                }}
            """)
            fl = QVBoxLayout(f)
            fl.setContentsMargins(12, 8, 12, 8)
            fl.setSpacing(4)
            hl = QHBoxLayout()
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            ic = QLabel()
            ic.setPixmap(qta.icon(icone, color=cor).pixmap(18, 18))
            hl.addWidget(ic)
            hl.addWidget(QLabel(rotulo, styleSheet=f"color: #90CAF9; font-size: 11px; font-weight: 600;"))
            hl.addStretch()
            fl.addLayout(hl)
            v = QLabel("0")
            v.setStyleSheet("color: #E0E0E0; font-size: 22px; font-weight: bold;")
            v.setAlignment(Qt.AlignCenter)
            fl.addWidget(v)
            self.stat_labels[chave] = v
            status_grid.addWidget(f)

        layout.addLayout(status_grid)

        # Backup card
        bk = QFrame()
        bk.setStyleSheet("""
            QFrame { background-color: #1a1a2e; border: 1px solid #2a2a4e;
                     border-radius: 10px; padding: 12px; margin-top: 4px; }
        """)
        bkl = QHBoxLayout(bk)
        self.bk_info = QLabel(_("Backup: checking..."))
        self.bk_info.setStyleSheet("color: #B0BEC5; font-size: 12px;")
        bkl.addWidget(self.bk_info, stretch=1)
        bkb = _mkbtn(_("  Backup"), "fa5s.archive", "#F57F17", "#F9A825")
        bkb.setMinimumHeight(32)
        bkb.clicked.connect(self._run_backup)
        bkl.addWidget(bkb)
        layout.addWidget(bk)

        # Divergências (schema changes)
        layout.addSpacing(4)
        self.div_frame = QFrame()
        self.div_frame.setStyleSheet("""
            QFrame { background-color: #1a1a2e; border: 1px solid #2a2a4e;
                     border-radius: 8px; padding: 8px 12px; margin-bottom: 4px; }
        """)
        divl = QHBoxLayout(self.div_frame)
        divl.setContentsMargins(8, 4, 8, 4)
        self.div_icon = QLabel()
        self.div_icon.setPixmap(qta.icon("fa5s.exclamation-triangle", color="#FFA726").pixmap(14, 14))
        divl.addWidget(self.div_icon)
        self.div_label = QLabel(_("No changes detected"))
        self.div_label.setStyleSheet("color: #607D8B; font-size: 11px; background: transparent;")
        divl.addWidget(self.div_label, stretch=1)
        self.div_frame.hide()
        layout.addWidget(self.div_frame)

        # Session history
        hist_title = QLabel(_("Session History"))
        hist_title.setStyleSheet("color: #90CAF9; font-size: 13px; font-weight: bold;")
        layout.addWidget(hist_title)
        self.hist_list = QListWidget()
        self.hist_list.setStyleSheet("""
            QListWidget {
                background-color: #0d1117; border: 1px solid #30363d;
                border-radius: 6px; color: #c9d1d9; font-size: 11px;
            }
            QListWidget::item { padding: 4px 8px; border-bottom: 1px solid #161b2e; }
        """)
        layout.addWidget(self.hist_list, stretch=1)

        self._atualizar_historico()

    def _ir_para_ns(self):
        if self._ns_pagina:
            self._ir_para(self._ns_pagina)

    def _ir_para(self, pagina):
        parent = self.parent()
        while parent:
            if hasattr(parent, '_show_page'):
                parent._show_page(pagina)
                break
            parent = parent.parent()

    def _run_backup(self):
        bm = BackupManager(self._db_path())
        path = bm.executar_backup()
        if path:
            registrar_operacao("backup", "Backup manual", "ok")
            self._atualizar_historico()
            self._atualizar_backup()

    def _atualizar_backup(self):
        bm = BackupManager(self._db_path())
        ultimo = bm.ultimo_backup()
        precisa = bm.precisa_backup()
        if ultimo:
            txt = _("Last backup: {date}").format(date=ultimo.strftime('%d/%m/%Y %H:%M'))
            txt += _("  (OK)") if not precisa else _("  (overdue)")
            self.bk_info.setText(txt)
        else:
            self.bk_info.setText(_("No backup found"))

    def _atualizar_historico(self):
        self.hist_list.clear()
        todos = _carregar_historico() + _historico_sessao
        # Últimos 20, sem duplicatas
        vistos = set()
        unicos = []
        for op in reversed(todos):
            chave = f"{op.timestamp}|{op.tipo}|{op.descricao}"
            if chave not in vistos:
                vistos.add(chave)
                unicos.append(op)
            if len(unicos) >= 20:
                break

        for op in unicos:
            ico, cor = _ICONES_TIPO.get(op.tipo, ("fa5s.circle", "#78909C"))
            marcador = "●" if op.status == "ok" else "✕"
            status_cor = "#4CAF50" if op.status == "ok" else "#EF5350"
            item = QListWidgetItem(
                f"  {op.timestamp}  |  {op.descricao}"
            )
            item.setForeground(QColor("#c9d1d9"))
            self.hist_list.addItem(item)

    def refresh(self):
        c = self.db.conn.cursor()
        for table in ["arquivos", "sheets", "raw_data"]:
            row = c.execute(f"SELECT COUNT(*) as t FROM {table}").fetchone()
            if table in self.stat_labels:
                self.stat_labels[table].setText(str(row["t"]))

        # Próximo passo — sempre mostra o PRÓXIMO, nunca "tudo pronto"
        n_arquivos = c.execute("SELECT COUNT(*) as t FROM arquivos").fetchone()["t"]
        n_fact = c.execute("SELECT COUNT(*) as t FROM fact_dados").fetchone()["t"]

        if n_arquivos == 0:
            msg = _("Start by importing your spreadsheets")
            ico = "fa5s.arrow-right"
            cor_ico = "#FFD54F"
            pagina = "importar"
        elif n_fact == 0:
            msg = _("Imported! Now adjust the inverted tables")
            ico = "fa5s.sync-alt"
            cor_ico = "#AB47BC"
            pagina = "transformar"
        else:
            msg = _("Data adjusted. Export or re-import if there's new data")
            ico = "fa5s.file-export"
            cor_ico = "#66BB6A"
            pagina = "exportar"

        self.ns_icon.setPixmap(qta.icon(ico, color=cor_ico).pixmap(18, 18))
        self.ns_label.setText(msg)
        self._ns_pagina = pagina
        self.ns_btn.show()

        # Divergências
        divs = c.execute("""
                         SELECT a.nome_arquivo, sa.colunas_adicionadas, sa.colunas_removidas, sa.detectado_em
                         FROM schema_audit sa
                                  JOIN sheets s ON sa.sheet_id = s.id
                                  JOIN arquivos a ON s.arquivo_id = a.id
                         ORDER BY sa.detectado_em DESC LIMIT 3
                         """).fetchall()
        if divs:
            txts = []
            for d in divs:
                adicionadas = len(json.loads(d["colunas_adicionadas"])) if d["colunas_adicionadas"] else 0
                removidas = len(json.loads(d["colunas_removidas"])) if d["colunas_removidas"] else 0
                txts.append(f"{d['nome_arquivo']}: +{adicionadas} -{removidas} colunas")
            self.div_label.setText(" | ".join(txts))
            self.div_frame.show()
        else:
            self.div_label.setText(_("No changes detected"))
            self.div_frame.hide()

        self._atualizar_backup()
        self._atualizar_historico()

    def retranslate_ui(self):
        self.ns_label.setText(_("Loading sheets..."))
        tip_import = _("Import spreadsheets")
        tip_ajustar = _("Adjust inverted tables")
        tip_export = _("Export corrected spreadsheets")
        self._update_card_tooltips(tip_import, tip_ajustar, tip_export)
        self.div_label.setText(_("No changes detected"))
        self.refresh()

    def _update_card_tooltips(self, tip_import, tip_ajustar, tip_export):
        pass  # cards stored in local vars in _build_ui — refresh handles texts

    def _on_log(self, text):
        pass


# ─────────────────────────────────────────────
#  Importar (unificado: scan + ingest)
# ─────────────────────────────────────────────
class ImportPage(BasePage):
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel(_("Import Spreadsheets"))
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #E0E0E0;")
        layout.addWidget(title)

        sub = QLabel(_("Drag a folder here or click to select. The system reads automatically."))
        sub.setStyleSheet("color: #78909C; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(sub)

        self.drop_label = QLabel()
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setFixedHeight(72)
        self.drop_label.setText(_("Drop your spreadsheet folder here\n  or click to select"))
        self.drop_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #30363d; border-radius: 12px;
                color: #546E7A; font-size: 13px;
                background-color: rgba(255,255,255,0.02);
                padding: 12px;
            }
            QLabel:hover {
                border-color: #42A5F5; color: #42A5F5;
                background-color: rgba(66,165,245,0.05);
            }
        """)
        self.drop_label.setAcceptDrops(True)
        self.drop_label.mousePressEvent = lambda e: self._browse()
        self.drop_label.dragEnterEvent = lambda e: self._on_drag(e)
        self.drop_label.dragLeaveEvent = lambda e: self._on_drag_leave(e)
        self.drop_label.dropEvent = lambda e: self._on_drop(e)
        self.drop_label.setToolTip(_("Click to select or drag a spreadsheet folder"))
        layout.addWidget(self.drop_label)

        path_row, self.path_edit, self.btn_browse = self._path_input(
            _("C:\\\\path\\\\to\\\\spreadsheets"), "fa5s.folder-open"
        )
        self.path_edit.setToolTip(_("Folder path. Use the selector or paste the path manually."))
        self.path_edit.textChanged.connect(self._on_path_typed)
        self.btn_browse.setToolTip(_("Select spreadsheet folder"))
        self.btn_browse.clicked.connect(self._browse)

        self._recent_model = QStringListModel()
        self._completer = QCompleter(self._recent_model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setMaxVisibleItems(8)
        self._completer.activated.connect(lambda t: self.path_edit.setText(t))
        self.path_edit.setCompleter(self._completer)
        self._refresh_recent()

        layout.addLayout(path_row)

        fmt_info = QLabel(_("Formats: .xlsx  .xlsb  .xlsm  .csv  .parquet"))
        fmt_info.setStyleSheet("color: #546E7A; font-size: 11px; margin-bottom: 12px;")
        layout.addWidget(fmt_info)

        # Step indicators
        steps = QHBoxLayout()
        self._step_labels = []
        for ico, txt in [("fa5s.search", _("Scanning...")), ("fa5s.download", _("Ingesting..."))]:
            f = QFrame()
            f.setStyleSheet("""
                QFrame { background-color: #1a1a2e; border: 1px solid #2a2a4e;
                         border-radius: 8px; padding: 8px; }
            """)
            fl = QHBoxLayout(f)
            fl.setContentsMargins(8, 4, 8, 4)
            ic = QLabel()
            ic.setPixmap(qta.icon(ico, color="#455A64").pixmap(16, 16))
            fl.addWidget(ic)
            lb = QLabel(txt)
            lb.setStyleSheet("color: #546E7A; font-size: 11px;")
            fl.addWidget(lb)
            steps.addWidget(f)
            self._step_labels.append((ic, lb, f))
        layout.addLayout(steps)

        self.btn_import = _mkbtn(_("  Import"), "fa5s.play", "#1565C0", "#1976D2")
        self.btn_import.setToolTip(_("Start import: automatic scan + ingest"))
        self.btn_import.setMinimumHeight(48)
        self.btn_import.clicked.connect(self._run_import)
        layout.addWidget(self.btn_import)

        self.progress = self._progress()
        layout.addWidget(self.progress)

        self.log = self._log_area()
        layout.addWidget(self.log, stretch=1)

    def _on_drag(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_label.setStyleSheet("""
                QLabel {
                    border: 3px dashed #4CAF50; border-radius: 12px;
                    color: #4CAF50; font-weight: bold;
                    background-color: rgba(76,175,80,0.10);
                    padding: 12px;
                }
            """)
            self.drop_label.setText(_("Drop here! Auto Scan + Ingest"))

    def _on_drag_leave(self, _):
        self.drop_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #30363d; border-radius: 12px;
                color: #546E7A; font-size: 13px;
                background-color: rgba(255,255,255,0.02);
                padding: 12px;
            }
            QLabel:hover {
                border-color: #42A5F5; color: #42A5F5;
                background-color: rgba(66,165,245,0.05);
            }
        """)
        self.drop_label.setText(_("Drop your spreadsheet folder here\n  or click to select"))

    def _on_drop(self, event):
        self._on_drag_leave(None)
        accepted = False
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            p = Path(path)
            if p.is_dir():
                self.path_edit.setText(str(p.absolute()))
                accepted = True
            elif p.suffix.lower() in (".xlsx", ".xlsb", ".xlsm", ".csv", ".parquet"):
                self.path_edit.setText(str(p.parent.absolute()))
                accepted = True
            break
        if accepted:
            self.drop_label.setStyleSheet("""
                QLabel {
                    border: 2px dashed #4CAF50; border-radius: 12px;
                    color: #4CAF50; background-color: rgba(76,175,80,0.06);
                    padding: 12px;
                }
                QLabel:hover { border-color: #66BB6A; color: #66BB6A; }
            """)
            self.drop_label.setText(_("Path selected!"))

    def _on_path_typed(self, text):
        if text and Path(text).exists():
            self.drop_label.setStyleSheet("""
                QLabel {
                    border: 2px dashed #4CAF50; border-radius: 12px;
                    color: #4CAF50; background-color: rgba(76,175,80,0.05);
                    padding: 12px;
                }
            """)
            self.drop_label.setText(_("Valid path"))
        else:
            self._on_drag_leave(None)

    def _refresh_recent(self):
        paths = _load_recent()
        self._recent_model.setStringList(paths)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, _("Spreadsheet folder"))
        if path:
            self.path_edit.setText(path)

    def _run_import(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, _("Warning"), _("Select or paste a path first."))
            return
        if not Path(path).exists():
            QMessageBox.critical(self, _("Error"), _("Caminho inválido: {path}").format(path=path))
            return
        _save_recent(path)
        self._refresh_recent()
        self._marcar_passo(0, False)
        self._marcar_passo(1, False)
        self.lock_controls(True)
        self._exec_worker(BothWorker(self._db_path(), path))

    def _marcar_passo(self, idx, done):
        if idx < len(self._step_labels):
            ic, lb, f = self._step_labels[idx]
            ico = "fa5s.check" if done else "fa5s.search"
            cor = "#4CAF50" if done else "#546E7A"
            ic.setPixmap(qta.icon(ico, color=cor).pixmap(16, 16))
            lb.setStyleSheet(f"color: {cor}; font-size: 11px; font-weight: {'bold' if done else 'normal'};")

    def lock_controls(self, locked: bool):
        self.btn_import.setEnabled(not locked)
        self.btn_browse.setEnabled(not locked)
        self.path_edit.setReadOnly(locked)

    def retranslate_ui(self):
        self.drop_label.setText(_("Drop your spreadsheet folder here\n  or click to select"))
        self.btn_import.setText(_("  Import"))
        for (ico, lb, frm), txt in zip(self._step_labels,
                                        [_("Scanning..."), _("Ingesting...")]):
            lb.setText(txt)

    def _on_log(self, text):
        self.log.append(text)

    def _on_progress(self, value, text):
        self.progress.setValue(value)
        if text:
            self.progress.setFormat(f"{value}% — {text}")
        else:
            self.progress.setFormat(f"{value}%")
        if value > 0:
            self._marcar_passo(0, True)
        if value >= 100:
            self._marcar_passo(1, True)

    def _on_finished(self, ok):
        self.progress.setValue(100 if ok else 0)
        self.lock_controls(False)
        if ok:
            self._marcar_passo(1, True)
            self.log.append("\n✅ Importação concluída!")
            registrar_operacao("importar", "Importação concluída", "ok")
            # Invalidar cache da pagina de transformacao
            parent = self.parent()
            while parent:
                if hasattr(parent, '_pages') and 'ajustar' in parent._pages:
                    parent._pages['ajustar'].invalidate_cache()
                    break
                parent = parent.parent()

    def _on_error(self, msg):
        self.progress.setValue(0)
        self.log.append(f"\n❌ {msg}")
        self.lock_controls(False)
        registrar_operacao("importar", f"Erro na importação", "erro")
        QMessageBox.critical(self, _("Error"), msg)


# ── Recent paths helpers ─────────────────────
_RECENT_FILE = Path.home() / "sheetpilot_db" / "recent_paths.json"


def _load_recent() -> list[str]:
    try:
        if _RECENT_FILE.exists():
            return json.loads(_RECENT_FILE.read_text(encoding="utf-8")).get("paths", [])
    except Exception:
        pass
    return []


def _save_recent(path: str):
    paths = _load_recent()
    path = str(Path(path).absolute())
    if path in paths: paths.remove(path)
    paths.insert(0, path)
    paths = paths[:10]
    try:
        _RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_FILE.write_text(json.dumps({"paths": paths}, indent=2), encoding="utf-8")
    except Exception:
        pass


# ─────────────────────────────────────────────
#  Ajustar
# ─────────────────────────────────────────────
class TransformPage(BasePage):
    def __init__(self, db, page_title="", parent=None):
        self._schema_cache: list[dict] | None = None
        super().__init__(db, page_title, parent)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel(_("Adjust Data"))
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #E0E0E0;")
        layout.addWidget(title)

        sub = QLabel(_("Convert inverted tables (dates as columns) to star format."))
        sub.setStyleSheet("color: #78909C; font-size: 12px; margin-bottom: 12px;")
        layout.addWidget(sub)

        self.schema_list = QListWidget()
        self.schema_list.setStyleSheet("""
            QListWidget {
                background-color: #0d1117; border: 1px solid #30363d;
                border-radius: 6px; color: #c9d1d9; font-size: 12px;
            }
            QListWidget::item:selected { background-color: #1565C0; }
            QListWidget::item { padding: 6px; }
        """)
        self.schema_list.setToolTip(_("Spreadsheets detected. Select one to transform."))
        layout.addWidget(self.schema_list, stretch=1)

        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #546E7A; font-size: 13px; padding: 24px;")
        self.empty_label.hide()
        layout.addWidget(self.empty_label)
        self._populate()

        btn_row = QHBoxLayout()
        self.btn_one = _mkbtn(_("Transform Selected"), "fa5s.sync-alt", "#1565C0", "#1976D2")
        self.btn_one.setToolTip(_("Applies unpivot to the selected sheet only"))
        self.btn_one.clicked.connect(self._run_one)
        self.btn_all = _mkbtn(_("Transform All"), "fa5s.forward", "#2E7D32", "#388E3C")
        self.btn_all.setToolTip(_("Applies unpivot to all sheets"))
        self.btn_all.clicked.connect(self._run_all)
        btn_row.addWidget(self.btn_one)
        btn_row.addWidget(self.btn_all)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.progress = self._progress()
        layout.addWidget(self.progress)

        self.log = self._log_area()
        layout.addWidget(self.log)

    def _populate(self):
        if self._schema_cache is not None:
            self._render_cache()
            return
        try:
            # Diagnostico
            total_sheets = self.db.conn.execute(
                "SELECT COUNT(*) as t FROM sheets"
            ).fetchone()["t"]
            total_arquivos = self.db.conn.execute(
                "SELECT COUNT(*) as t FROM arquivos"
            ).fetchone()["t"]
            total_raw = self.db.conn.execute(
                "SELECT COUNT(*) as t FROM raw_data"
            ).fetchone()["t"]
            logger.info(
                "TransformPage: sheets=%d, arquivos=%d, raw_data=%d",
                total_sheets, total_arquivos, total_raw
            )

            rows = self.db.conn.execute("""
                                        SELECT DISTINCT s.schema_hash, a.nome_arquivo, s.nome_sheet, s.qtd_linhas
                                        FROM sheets s
                                                 JOIN arquivos a ON s.arquivo_id = a.id
                                        WHERE s.schema_hash IS NOT NULL
                                        ORDER BY s.ultimo_hash_modificado DESC
                                        """).fetchall()
            self._schema_cache = [dict(r) for r in rows]
            self._render_cache()
            if not rows:
                logger.info(
                    "Nenhuma planilha para transformar: sheets=%d, "
                    "arquivos=%d, raw_data=%d",
                    total_sheets, total_arquivos, total_raw
                )
        except Exception as e:
            logger.error("Erro ao popular lista de schemas: %s", e)

    def _render_cache(self):
        self.schema_list.clear()
        if not self._schema_cache:
            self.empty_label.setText(_("No sheets to transform."))
            self.empty_label.show()
            self.schema_list.hide()
            return
        self.empty_label.hide()
        self.schema_list.show()
        for r in self._schema_cache:
            txt = f"{r['nome_arquivo']}  ›  {r['nome_sheet']}  ({r['qtd_linhas']} linhas)"
            item = QListWidgetItem(txt)
            item.setData(Qt.UserRole, r["schema_hash"])
            item.setToolTip(
                f"Arquivo: {r['nome_arquivo']}\n"
                f"Planilha: {r['nome_sheet']}\n"
                f"Linhas: {r['qtd_linhas']}"
            )
            self.schema_list.addItem(item)

    def invalidate_cache(self):
        self._schema_cache = None

    def _run_one(self):
        item = self.schema_list.currentItem()
        if not item:
            QMessageBox.warning(self, _("Warning"), _("Select a sheet from the list."))
            return
        hid = item.data(Qt.UserRole)
        self.lock_controls(True)
        self._exec_worker(TransformWorker(self._db_path(), hid))

    def _run_all(self):
        qnt = self.schema_list.count()
        if qnt == 0:
            QMessageBox.information(self, _("Warning"), _("No sheets to transform."))
            return
        msg = _("Apply unpivot to all {count} sheet(s)? Already transformed data will be overwritten.").format(
            count=qnt)
        confirm = QMessageBox.question(self, _("Confirm"), msg, QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        self.lock_controls(True)
        self._exec_worker(TransformWorker(self._db_path()))

    def refresh(self):
        self.invalidate_cache()
        self._populate()

    def lock_controls(self, locked: bool):
        self.btn_one.setEnabled(not locked)
        self.btn_all.setEnabled(not locked)
        self.schema_list.setEnabled(not locked)

    def retranslate_ui(self):
        self.btn_one.setText(_("  Transform Selected"))
        self.btn_all.setText(_("  Transform All"))
        self.schema_list.setToolTip(_("Select a sheet from the list."))

    def _on_log(self, text):
        self.log.append(text)

    def _on_progress(self, value, text):
        self.progress.setValue(value)
        self.progress.setFormat(f"{value}%" if not text else f"{value}% — {text}")

    def _on_finished(self, ok):
        self.progress.setValue(100 if ok else 0)
        self.lock_controls(False)
        self.invalidate_cache()
        self._populate()
        if ok:
            self.log.append("\n✅ Transformação concluída!")
            registrar_operacao("ajustar", "Transformação concluída", "ok")

    def _on_log(self, text):
        self.log.append(text)

    def _on_progress(self, value, text):
        self.progress.setValue(value)
        if text:
            self.progress.setFormat(f"{value}% — {text}")
        else:
            self.progress.setFormat(f"{value}%")


# ─── ExportPage ──────────────────────────────

EXPORT_DIR_DEFAULT = str(Path.home() / "sheetpilot_db" / "exports")


class ExportPage(BasePage):
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel(_("Export Data"))
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #E0E0E0;")
        layout.addWidget(title)

        sub = QLabel(_("One corrected sheet per original file. No internal codes, dates dd/mm/yyyy."))
        sub.setStyleSheet("color: #78909C; font-size: 12px; margin-bottom: 16px;")
        layout.addWidget(sub)

        out_row, self.out_edit, self.out_btn = self._path_input(EXPORT_DIR_DEFAULT, "fa5s.folder-open")
        self.out_edit.setText(EXPORT_DIR_DEFAULT)
        self.out_edit.setToolTip(_("Folder where exported files will be saved"))
        self.out_btn.setToolTip(_("Select destination folder"))
        self.out_btn.clicked.connect(self._browse_out)
        layout.addLayout(out_row)

        fmt_card = QFrame()
        fmt_card.setStyleSheet("""
            QFrame { background-color: #1a1a2e; border: 1px solid #2a2a4e;
                     border-radius: 10px; padding: 16px; margin: 8px 0; }
        """)
        fmtl = QVBoxLayout(fmt_card)
        fl1 = QHBoxLayout()
        lbl_fmt = QLabel(_("Output format"))
        lbl_fmt.setStyleSheet("color: #90CAF9; font-size: 13px; font-weight: bold;")
        fl1.addWidget(lbl_fmt)
        fl1.addStretch()
        fmtl.addLayout(fl1)

        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems([_("xlsx  (Standard Excel)"), _("xlsb  (Binary Excel)"), _("csv  (text)"), _("parquet  (columnar)")])
        self.fmt_combo.setCurrentIndex(0)
        self.fmt_combo.setStyleSheet("""
            QComboBox {
                background-color: #0d1117; color: #c9d1d9;
                border: 1px solid #30363d; border-radius: 6px;
                padding: 8px 12px; font-size: 13px; min-width: 260px;
            }
            QComboBox::drop-down { border: none; width: 30px; }
            QComboBox::down-arrow {
                border-left: 6px solid transparent;
                border-right: 6px solid transparent;
                border-top: 6px solid #607D8B; margin-right: 8px;
            }
            QComboBox:hover { border-color: #42A5F5; }
        """)
        self.fmt_combo.setToolTip(_("xlsx = Standard Excel  |  xlsb = Binary Excel  |  csv = text  |  parquet = columnar"))
        fmtl.addWidget(self.fmt_combo)

        self.lbl_sheets = QLabel(_("Loading sheets..."))
        self.lbl_sheets.setStyleSheet("color: #607D8B; font-size: 12px; margin-top: 6px;")
        fmtl.addWidget(self.lbl_sheets)
        layout.addWidget(fmt_card)

        self.sheet_list = QListWidget()
        self.sheet_list.setStyleSheet("""
            QListWidget {
                background-color: #0d1117; border: 1px solid #30363d;
                border-radius: 8px; color: #c9d1d9; font-size: 12px;
                max-height: 160px;
            }
            QListWidget::item { padding: 6px 10px; }
            QListWidget::item:selected { background-color: #1565C0; }
        """)
        self.sheet_list.setToolTip(_("Available sheets for export"))
        layout.addWidget(self.sheet_list)

        self.btn_export = _mkbtn(_("  Export All"), "fa5s.file-export", "#2E7D32", "#388E3C")
        self.btn_export.setToolTip(_("Generates one file per original sheet, no IDs, dd/mm/yyyy dates"))
        self.btn_export.setMinimumHeight(50)
        self.btn_export.clicked.connect(self._run_export)
        layout.addWidget(self.btn_export)

        self.progress = self._progress()
        layout.addWidget(self.progress)

        self.log = self._log_area()
        layout.addWidget(self.log, stretch=1)

    def refresh(self):
        self._list_arquivos()

    def _list_arquivos(self):
        self.sheet_list.clear()
        try:
            c = self.db.conn.cursor()
            arquivos = c.execute(ARQUIVOS_SQL).fetchall()
            if not arquivos:
                self.lbl_sheets.setText(_("No data. Import and transform first."))
                return
            total_geral = 0
            total_items = 0
            for arq in arquivos:
                dim_id = arq["arq_id"]
                orig_id = arquivo_id_para_raw(c, dim_id)

                fact_sheets = c.execute(
                    "SELECT DISTINCT sheet_name FROM fact_dados WHERE arquivo_id = ?",
                    (dim_id,)
                ).fetchall()

                raw_sheets = []
                if orig_id is not None:
                    raw_sheets = c.execute("""
                                           SELECT DISTINCT s.nome_sheet
                                           FROM raw_data rd
                                                    JOIN sheets s ON rd.sheet_id = s.id
                                           WHERE rd.arquivo_id = ?
                                           EXCEPT
                                           SELECT DISTINCT f.sheet_name
                                           FROM fact_dados f
                                           WHERE f.arquivo_id = ?
                                           """, (orig_id, dim_id)).fetchall()

                for s in fact_sheets:
                    cnt = c.execute(
                        "SELECT COUNT(*) as t FROM fact_dados WHERE arquivo_id = ? AND sheet_name = ?",
                        (dim_id, s["sheet_name"]),
                    ).fetchone()
                    qtd = cnt["t"]
                    total_geral += qtd
                    label = f"{arq['nome_arquivo']}  ›  {s['sheet_name']}  ({qtd} linhas) ✓ corrigida"
                    item = QListWidgetItem(label)
                    item.setData(Qt.UserRole, ("fact", dim_id, s["sheet_name"], arq["nome_arquivo"]))
                    item.setToolTip(_("Fixed sheet (inverted -> normalized)"))
                    self.sheet_list.addItem(item)
                    total_items += 1

                for s in raw_sheets:
                    cnt = c.execute(
                        "SELECT COUNT(*) as t FROM raw_data rd "
                        "WHERE rd.arquivo_id = ? AND rd.sheet_id = ("
                        "  SELECT id FROM sheets WHERE arquivo_id = ? AND nome_sheet = ?"
                        ")",
                        (orig_id, orig_id, s["nome_sheet"]),
                    ).fetchone()
                    qtd = cnt["t"]
                    total_geral += qtd
                    label = f"{arq['nome_arquivo']}  ›  {s['nome_sheet']}  ({qtd} linhas) — original"
                    item = QListWidgetItem(label)
                    item.setData(Qt.UserRole, ("raw", dim_id, s["nome_sheet"], arq["nome_arquivo"], orig_id))
                    item.setToolTip(_("Already in correct format"))
                    self.sheet_list.addItem(item)
                    total_items += 1

            self.lbl_sheets.setText(_("{total_items} sheet(s) · {total_geral} total rows").format(
                total_items=total_items, total_geral=total_geral))
        except Exception as e:
            self.lbl_sheets.setText(f"Error: {e}")
            import traceback
            self.lbl_sheets.setToolTip(traceback.format_exc())

    def _browse_out(self):
        path = QFileDialog.getExistingDirectory(self, _("Destination folder"))
        if path:
            self.out_edit.setText(path)

    def _fmt_key(self) -> str:
        raw = self.fmt_combo.currentText()
        if "xlsx" in raw:
            return "xlsx"
        if "xlsb" in raw:
            return "xlsb"
        if "csv" in raw:
            return "csv"
        return "parquet"

    def _run_export(self):
        dest = self.out_edit.text().strip()
        if not dest:
            QMessageBox.warning(self, _("Warning"), _("Select a destination folder first."))
            return
        if not Path(dest).exists():
            try:
                Path(dest).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, _("Error"), _("Could not create: {dest}").format(dest=dest))
                return

        fmt = self._fmt_key()
        self.log.append(_("\nExporting as {fmt}...").format(fmt=fmt.upper()))
        self.lock_controls(True)
        self.progress.setValue(0)
        self._exec_worker(ExportWorker(self._db_path(), dest, fmt))

    def lock_controls(self, locked: bool):
        self.btn_export.setEnabled(not locked)
        self.out_btn.setEnabled(not locked)
        self.out_edit.setReadOnly(locked)

    def retranslate_ui(self):
        self.btn_export.setText(_("  Export All"))
        self.fmt_combo.clear()
        self.fmt_combo.addItems([_("xlsx  (Excel padrão)"), _("xlsb  (Binary Excel)"), _("csv  (text)"), _("parquet  (columnar)")])

    def _on_log(self, text):
        self.log.append(text)

    def _on_progress(self, value, text):
        self.progress.setValue(value)

    def _on_finished(self, ok):
        self.progress.setValue(100 if ok else 0)
        self.lock_controls(False)
        if ok:
            dest = self.out_edit.text().strip()
            self.log.append(_("\nExport complete!"))
            registrar_operacao("exportar", "Export completed", "ok")
            try:
                import subprocess
                subprocess.Popen(["explorer", str(dest)])
            except Exception:
                pass

    def _on_error(self, msg):
        self.progress.setValue(0)
        self.log.append(f"\n✖ {msg}")
        self.lock_controls(False)
        registrar_operacao("exportar", "Export error", "erro")
        QMessageBox.critical(self, _("Error"), msg)


# ─────────────────────────────────────────────
#  Exportar
# ─────────────────────────────────────────────
EXPORT_DIR_DEFAULT = str(Path.home() / "sheetpilot_db" / "exports")


# ─────────────────────────────────────────────
#  Configurações
# ─────────────────────────────────────────────
class SettingsPage(BasePage):
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel(_("Settings"))
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #E0E0E0;")
        layout.addWidget(title)
        layout.addSpacing(12)

        # Database info
        grp_db = QGroupBox(_("Database"))
        grp_db.setStyleSheet("""
            QGroupBox { color: #90CAF9; font-size: 13px; font-weight: bold;
                        border: 1px solid #2a2a4e; border-radius: 8px;
                        margin-top: 12px; padding: 16px; }
        """)
        dbl = QVBoxLayout(grp_db)
        dbp = QLabel(f"{_('Path')}: {self.db.db_path}")
        dbp.setStyleSheet("color: #B0BEC5; font-size: 12px;")
        dbp.setWordWrap(True)
        dbp.setToolTip(_("SQLite database file location"))
        dbl.addWidget(dbp)

        sz = "?"
        try:
            sz = f"{Path(self.db.db_path).stat().st_size / 1024:.1f} KB"
        except OSError:
            pass
        dbl.addWidget(QLabel(f"{_('Size')}: {sz}", styleSheet="color: #B0BEC5; font-size: 12px;"))

        btn_bkup = _mkbtn(_("  Manage Backups"), "fa5s.archive", "#F57F17", "#F9A825")
        btn_bkup.setToolTip(_("List, restore or delete backups"))
        btn_bkup.clicked.connect(self._show_backups)
        dbl.addWidget(btn_bkup)
        layout.addWidget(grp_db)

        # Language
        grp_lang = QGroupBox(_("Language"))
        grp_lang.setStyleSheet("""
            QGroupBox { color: #90CAF9; font-size: 13px; font-weight: bold;
                        border: 1px solid #2a2a4e; border-radius: 8px;
                        margin-top: 12px; padding: 16px; }
        """)
        langl = QVBoxLayout(grp_lang)
        self.lang_combo = QComboBox()
        self.lang_combo.setStyleSheet("""
            QComboBox {
                background-color: #0d1117; color: #c9d1d9;
                border: 1px solid #30363d; border-radius: 6px;
                padding: 8px 12px; font-size: 12px;
            }
        """)
        from src.localization import available_languages, current_language
        self.lang_combo.blockSignals(True)
        current_code = current_language()
        selected_idx = 0
        for i, (code, name) in enumerate(available_languages()):
            self.lang_combo.addItem(f"{name} ({code})", code)
            if code == current_code:
                selected_idx = i
        self.lang_combo.setCurrentIndex(selected_idx)
        self.lang_combo.blockSignals(False)
        self.lang_combo.currentIndexChanged.connect(self._change_language)
        langl.addWidget(self.lang_combo)
        layout.addWidget(grp_lang)

        # Backup list
        self.bk_list = QListWidget()
        self.bk_list.setStyleSheet("""
            QListWidget { background-color: #0d1117; border: 1px solid #30363d;
                          border-radius: 6px; color: #c9d1d9; font-size: 12px;
                          max-height: 180px; }
            QListWidget::item { padding: 4px; }
            QListWidget::item:selected { background-color: #1565C0; }
        """)
        self._refresh_backups()
        layout.addWidget(self.bk_list)

        bk_actions = QHBoxLayout()
        btn_restore = _mkbtn(_("  Restore"), "fa5s.undo", "#E65100", "#EF6C00")
        btn_restore.setToolTip(_("Replaces current database with the selected backup (useful for recovery)"))
        btn_restore.clicked.connect(self._restore)
        lbl_auto = QLabel(_("Old backups (>30 days) are removed automatically during cleanup."))
        lbl_auto.setStyleSheet("color: #546E7A; font-size: 11px;")
        bk_actions.addWidget(btn_restore)
        bk_actions.addWidget(lbl_auto)
        bk_actions.addStretch()
        layout.addLayout(bk_actions)

        # Maintenance
        grp_mnt = QGroupBox(_("Maintenance & Cleanup"))
        grp_mnt.setStyleSheet("""
            QGroupBox { color: #90CAF9; font-size: 13px; font-weight: bold;
                        border: 1px solid #2a2a4e; border-radius: 8px;
                        margin-top: 12px; padding: 16px; }
        """)
        mntl = QVBoxLayout(grp_mnt)
        self.cleanup_info = QLabel(_("Click 'Analyze' to see what can be optimized"))
        self.cleanup_info.setStyleSheet("color: #B0BEC5; font-size: 12px;")
        self.cleanup_info.setWordWrap(True)
        mntl.addWidget(self.cleanup_info)
        mnt_actions = QHBoxLayout()
        btn_analyze = _mkbtn(_("  Analyze"), "fa5s.stethoscope", "#546E7A", "#607D8B")
        btn_analyze.setToolTip(_("Analyzes the database and shows how much space can be recovered"))
        btn_analyze.clicked.connect(self._analyze_db)
        btn_clean = _mkbtn(_("  Clean & Optimize"), "fa5s.broom", "#2E7D32", "#388E3C")
        btn_clean.setToolTip(_("Removes orphan data, duplicates and old backups. Runs VACUUM."))
        btn_clean.clicked.connect(self._run_cleanup)
        mnt_actions.addWidget(btn_analyze)
        mnt_actions.addWidget(btn_clean)
        mnt_actions.addStretch()
        mntl.addLayout(mnt_actions)
        layout.addWidget(grp_mnt)

        # Export config
        grp_exp = QGroupBox(_("Default Export"))
        grp_exp.setStyleSheet("""
            QGroupBox { color: #90CAF9; font-size: 13px; font-weight: bold;
                        border: 1px solid #2a2a4e; border-radius: 8px;
                        margin-top: 12px; padding: 16px; }
        """)
        expl = QVBoxLayout(grp_exp)
        self.exp_path_edit = QLineEdit(EXPORT_DIR_DEFAULT)
        self.exp_path_edit.setStyleSheet("""
            QLineEdit { padding: 8px 12px; border: 1px solid #30363d;
                        border-radius: 6px; background-color: #0d1117;
                        color: #c9d1d9; font-size: 12px; }
        """)
        self.exp_path_edit.setToolTip(_("Default export folder"))
        expl.addWidget(QLabel(_("Export folder:"), styleSheet="color: #B0BEC5; font-size: 12px;"))
        expl.addWidget(self.exp_path_edit)
        layout.addWidget(grp_exp)

        layout.addStretch()

    def _change_language(self, idx: int):
        code = self.lang_combo.itemData(idx)
        if code:
            from src.localization import set_language, trigger_refresh
            set_language(code)
            trigger_refresh()
            QMessageBox.information(self, _("SheetPilot"),
                                    _("Language changed. Navigate to other pages to see the changes, or restart the application."))

    def retranslate_ui(self):
        self.cleanup_info.setText(_("Click 'Analyze' to see what can be optimized"))

    def _refresh_backups(self):
        self.bk_list.clear()
        bm = BackupManager(self._db_path())
        for b in bm.listar_backups():
            item = QListWidgetItem(f"{b['nome']}  ({b['tamanho_kb']} KB)")
            item.setData(Qt.UserRole, b["caminho"])
            item.setToolTip(f"Criado: {b['data'][:19]}")
            self.bk_list.addItem(item)

    def _show_backups(self):
        self._refresh_backups()

    def _restore(self):
        item = self.bk_list.currentItem()
        if not item:
            QMessageBox.warning(self, _("Warning"), _("Select a backup from the list."))
            return
        path = item.data(Qt.UserRole)
        confirm = QMessageBox.question(self, _("Restore"),
                                       _("Isso substituirá o banco atual. Continuar?"),
                                       QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            bm = BackupManager(self._db_path())
            if bm.restaurar_backup(path):
                QMessageBox.information(self, _("Success"), _("Restored. Restart."))
            else:
                QMessageBox.critical(self, _("Error"), _("Failed to restore."))

    def _analyze_db(self):
        try:
            dc = DatabaseCleanup(self._db_path())
            diag = dc.diagnostic()
            raw = diag["raw_orfao"];
            audit = diag["audit_total"]
            dup = diag["duplicatas"];
            size = diag["tamanho_atual_kb"]
            lines = [
                _("Size: {size:.1f} KB").format(size=size),
                _("Orphaned raw data: {n}").format(n=raw),
                _("Audit records: {n}").format(n=audit),
                _("Duplicates: {n}").format(n=dup),
            ]
            if raw > 0 or dup > 0:
                lines.append(_("Cleanup recommended."))
                self.cleanup_info.setText("\n".join(lines))
                self.cleanup_info.setStyleSheet("color: #FFB74D; font-size: 12px;")
            else:
                lines.append(_("Database healthy."))
                self.cleanup_info.setText("\n".join(lines))
                self.cleanup_info.setStyleSheet("color: #81C784; font-size: 12px;")
        except Exception as e:
            self.cleanup_info.setText(_("Error: {e}").format(e=e))
            self.cleanup_info.setStyleSheet("color: #EF5350; font-size: 12px;")

    def _run_cleanup(self):
        confirm = QMessageBox.question(self, _("Cleanup"),
                                       _("Remove raw data already transformed, duplicates and old backups?"),
                                       QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes: return
        self.cleanup_info.setText(_("Cleaning..."))
        try:
            dc = DatabaseCleanup(self._db_path())
            stats = dc.run_cleanup()
            lines = [
                _("Raw removed: {n}").format(n=stats['removidos_raw']),
                _("Audit cleaned: {n}").format(n=stats['removidos_audit']),
                _("Duplicates: {n}").format(n=stats['removidos_dup']),
                _("Backups deleted: {n}").format(n=stats['backups_excluidos']),
                _("Size: {a} -> {b} KB").format(a=stats['tamanho_antes_kb'], b=stats['tamanho_depois_kb']),
                _("Saved: {n} KB").format(n=stats['economia_kb']),
            ]
            self.cleanup_info.setText("\n".join(lines))
            self.cleanup_info.setStyleSheet("color: #81C784; font-size: 12px; font-weight: bold;")
            QMessageBox.information(self, _("Success"),
                                    _("Cleanup complete! {n} KB recovered.").format(n=stats['economia_kb']))
            registrar_operacao("limpeza", _("Cleanup: {n} KB recovered").format(n=stats['economia_kb']), "ok")
        except Exception as e:
            self.cleanup_info.setText(f"Erro: {e}")
            QMessageBox.critical(self, _("Error"), str(e))
