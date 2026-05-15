import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QTextEdit, QTreeWidget, QTreeWidgetItem,
    QGroupBox, QGridLayout, QProgressBar, QMessageBox, QCheckBox,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QComboBox,
    QScrollArea, QCompleter
)
from PySide6.QtCore import Qt, Signal, QSize, QStringListModel
from PySide6.QtGui import QFont, QColor
import qtawesome as qta

from src.gui.workers import (
    ScanWorker, IngestWorker, BothWorker,
    TransformWorker, FullPipelineWorker
)
from src.gui.backup import BackupManager, DatabaseCleanup


# ── Histórico de operações da sessão ─────────
_LOG_FILE = Path.home() / "planilha_bi_db" / "historico.json"

@dataclass
class Operacao:
    tipo: str       # "importar", "ajustar", "exportar", "backup", "limpeza"
    descricao: str
    status: str     # "ok", "erro"
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

    def _build_ui(self):
        raise NotImplementedError

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
            QMessageBox.warning(self, "Aviso", "Operação em andamento.")
            return
        self._worker = worker
        self._worker.log.connect(self._on_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.erro.connect(self._on_error)
        self._worker.start()

    def _on_log(self, text): pass
    def _on_progress(self, value, text): pass
    def _on_finished(self, ok): pass
    def _on_error(self, msg):
        QMessageBox.critical(self, "Erro", msg)


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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        # Welcome
        welcome = QLabel("Planilha BI Pilot")
        welcome.setStyleSheet("font-size: 24px; font-weight: bold; color: #E0E0E0;")
        layout.addWidget(welcome)

        sub = QLabel("Central de tratamento e correção de planilhas")
        sub.setStyleSheet("color: #78909C; font-size: 13px; margin-bottom: 12px;")
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
        self.ns_label = QLabel("Carregando...")
        self.ns_label.setStyleSheet("color: #B0BEC5; font-size: 12px; background: transparent;")
        nsl.addWidget(self.ns_label, stretch=1)
        self.ns_btn = QPushButton("Ir")
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
        acoes.setSpacing(12)
        for texto, icone, cor, dica, pagina in [
            ("Importar", "fa5s.file-import", "#1976D2", "Importar planilhas da pasta", "importar"),
            ("Ajustar", "fa5s.sync-alt", "#7B1FA2", "Ajustar planilhas invertidas", "transformar"),
            ("Exportar", "fa5s.file-export", "#388E3C", "Exportar planilhas corrigidas", "exportar"),
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
            ic = QLabel()
            ic.setPixmap(qta.icon(icone, color=cor).pixmap(32, 32))
            ic.setAlignment(Qt.AlignCenter)
            cl.addWidget(ic)
            lb = QLabel(texto)
            lb.setAlignment(Qt.AlignCenter)
            lb.setStyleSheet(f"color: #E0E0E0; font-size: 14px; font-weight: bold; margin-top: 4px;")
            cl.addWidget(lb)
            card.mousePressEvent = lambda e, p=pagina: self._ir_para(p)
            card.setToolTip(dica)
            acoes.addWidget(card)

        layout.addLayout(acoes)

        # Status cards (apenas 3 simples)
        self.stat_labels = {}
        status_grid = QHBoxLayout()
        for chave, rotulo, icone, cor in [
            ("arquivos", "Arquivos", "fa5s.file-excel", "#2196F3"),
            ("sheets", "Planilhas", "fa5s.table", "#4CAF50"),
            ("raw_data", "Linhas lidas", "fa5s.database", "#FF9800"),
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
            hl = QHBoxLayout()
            hl.setContentsMargins(0, 0, 0, 0)
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
        self.bk_info = QLabel("Backup: verificando...")
        self.bk_info.setStyleSheet("color: #B0BEC5; font-size: 12px;")
        bkl.addWidget(self.bk_info, stretch=1)
        bkb = _mkbtn("  Backup", "fa5s.archive", "#F57F17", "#F9A825")
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
        self.div_label = QLabel("Nenhuma divergência detectada")
        self.div_label.setStyleSheet("color: #607D8B; font-size: 11px; background: transparent;")
        divl.addWidget(self.div_label, stretch=1)
        self.div_frame.hide()
        layout.addWidget(self.div_frame)

        # Session history
        layout.addSpacing(6)
        hist_title = QLabel("Histórico da sessão")
        hist_title.setStyleSheet("color: #90CAF9; font-size: 13px; font-weight: bold;")
        layout.addWidget(hist_title)
        layout.addSpacing(3)
        self.hist_list = QListWidget()
        self.hist_list.setStyleSheet("""
            QListWidget {
                background-color: #0d1117; border: 1px solid #30363d;
                border-radius: 6px; color: #c9d1d9; font-size: 11px;
                max-height: 160px;
            }
            QListWidget::item { padding: 4px 8px; border-bottom: 1px solid #161b2e; }
        """)
        layout.addWidget(self.hist_list)
        layout.addSpacing(8)

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
            txt = f"Último backup: {ultimo.strftime('%d/%m/%Y %H:%M')}"
            txt += "  (OK)" if not precisa else "  (atrasado)"
            self.bk_info.setText(txt)
        else:
            self.bk_info.setText("Nenhum backup encontrado")

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
            msg = "Comece importando suas planilhas"
            ico = "fa5s.arrow-right"
            cor_ico = "#FFD54F"
            pagina = "importar"
        elif n_fact == 0:
            msg = "Importadas. Agora ajuste as tabelas invertidas"
            ico = "fa5s.sync-alt"
            cor_ico = "#AB47BC"
            pagina = "transformar"
        else:
            msg = "Dados ajustados. Exporte as planilhas corrigidas ou reimporte se houver novidades"
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
            ORDER BY sa.detectado_em DESC
            LIMIT 3
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
            self.div_label.setText("Nenhuma divergência detectada")
            self.div_frame.hide()

        self._atualizar_backup()
        self._atualizar_historico()

    def _on_log(self, text): pass


# ─────────────────────────────────────────────
#  Importar (unificado: scan + ingest)
# ─────────────────────────────────────────────
class ImportPage(BasePage):
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Importar Planilhas")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #E0E0E0;")
        layout.addWidget(title)

        sub = QLabel("Arraste uma pasta aqui ou clique em Selecionar. O sistema lê automaticamente.")
        sub.setStyleSheet("color: #78909C; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(sub)

        # Drop zone
        self.drop_label = QLabel("  Solte sua pasta de planilhas aqui  ")
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setFixedHeight(60)
        self.drop_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #30363d; border-radius: 12px;
                color: #546E7A; font-size: 13px; background-color: rgba(255,255,255,0.02);
            }
            QLabel:hover { border-color: #42A5F5; color: #42A5F5;
                           background-color: rgba(66,165,245,0.05); }
        """)
        self.drop_label.setAcceptDrops(True)
        self.drop_label.mousePressEvent = lambda e: self._browse()
        self.drop_label.dragEnterEvent = lambda e: self._on_drag(e)
        self.drop_label.dragLeaveEvent = lambda e: self._on_drag_leave(e)
        self.drop_label.dropEvent = lambda e: self._on_drop(e)
        self.drop_label.setToolTip("Clique para selecionar ou arraste uma pasta de planilhas")
        layout.addWidget(self.drop_label)

        path_row, self.path_edit, self.btn_browse = self._path_input(
            "C:\\caminho\\para\\planilhas", "fa5s.folder-open"
        )
        self.path_edit.setToolTip("Caminho da pasta. Use o seletor ou cole o caminho manualmente")
        self.path_edit.textChanged.connect(self._on_path_typed)
        self.btn_browse.setToolTip("Selecionar pasta com planilhas")
        self.btn_browse.clicked.connect(self._browse)

        self._recent_model = QStringListModel()
        self._completer = QCompleter(self._recent_model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setMaxVisibleItems(8)
        self._completer.activated.connect(lambda t: self.path_edit.setText(t))
        self.path_edit.setCompleter(self._completer)
        self._refresh_recent()

        layout.addLayout(path_row)

        fmt_info = QLabel("Formatos: .xlsx  ›  .xlsb  ›  .csv  ›  .parquet")
        fmt_info.setStyleSheet("color: #546E7A; font-size: 11px; margin-bottom: 12px;")
        layout.addWidget(fmt_info)

        # Step indicators
        steps = QHBoxLayout()
        self._step_labels = []
        for ico, txt in [("fa5s.search", "Escaneando..."), ("fa5s.download", "Ingerindo...")]:
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

        self.btn_import = _mkbtn("  Importar", "fa5s.play", "#1565C0", "#1976D2")
        self.btn_import.setToolTip("Inicia a importação: scan + ingest automáticos")
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
                    border: 2px dashed #42A5F5; border-radius: 12px;
                    color: #42A5F5; background-color: rgba(66,165,245,0.08);
                }
            """)

    def _on_drag_leave(self, _):
        self.drop_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #30363d; border-radius: 12px;
                color: #546E7A; background-color: rgba(255,255,255,0.02);
            }
            QLabel:hover { border-color: #42A5F5; color: #42A5F5;
                           background-color: rgba(66,165,245,0.05); }
        """)

    def _on_drop(self, event):
        self._on_drag_leave(None)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            p = Path(path)
            if p.is_dir():
                self.path_edit.setText(str(p.absolute()))
            elif p.suffix.lower() in (".xlsx", ".xlsb", ".csv", ".parquet"):
                self.path_edit.setText(str(p.parent.absolute()))
            break

    def _refresh_recent(self):
        paths = _load_recent()
        self._recent_model.setStringList(paths)

    def _on_path_typed(self, text):
        if text and Path(text).exists():
            self.drop_label.setStyleSheet("""
                QLabel {
                    border: 2px dashed #4CAF50; border-radius: 12px;
                    color: #4CAF50; background-color: rgba(76,175,80,0.05);
                }
            """)
        else:
            self._on_drag_leave(None)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Pasta com planilhas")
        if path:
            self.path_edit.setText(path)

    def _run_import(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Aviso", "Selecione ou cole um caminho primeiro.")
            return
        if not Path(path).exists():
            QMessageBox.critical(self, "Erro", f"Caminho inválido: {path}")
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

    def _on_log(self, text): self.log.append(text)

    def _on_progress(self, value, text):
        self.progress.setValue(value)
        self.progress.setFormat(f"{value}%")
        if value > 0: self._marcar_passo(0, True)
        if value >= 100: self._marcar_passo(1, True)

    def _on_finished(self, ok):
        self.progress.setValue(100 if ok else 0)
        self.lock_controls(False)
        if ok:
            self._marcar_passo(1, True)
            self.log.append("\n✅ Importação concluída!")
            registrar_operacao("importar", "Importação concluída", "ok")

    def _on_error(self, msg):
        self.progress.setValue(0)
        self.log.append(f"\n❌ {msg}")
        self.lock_controls(False)
        registrar_operacao("importar", f"Erro na importação", "erro")
        QMessageBox.critical(self, "Erro", msg)


# ── Recent paths helpers ─────────────────────
_RECENT_FILE = Path.home() / "planilha_bi_db" / "recent_paths.json"

def _load_recent() -> list[str]:
    try:
        if _RECENT_FILE.exists():
            return json.loads(_RECENT_FILE.read_text(encoding="utf-8")).get("paths", [])
    except Exception: pass
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
    except Exception: pass


# ─────────────────────────────────────────────
#  Ajustar
# ─────────────────────────────────────────────
class TransformPage(BasePage):
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Ajustar Dados")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #E0E0E0;")
        layout.addWidget(title)

        sub = QLabel("Converta planilhas invertidas (datas como colunas) para o formato estrela.")
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
        self.schema_list.setToolTip("Planilhas detectadas. Selecione uma para transformar.")
        self._populate()
        layout.addWidget(self.schema_list, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_one = _mkbtn("  Ajustar Selecionado", "fa5s.sync-alt", "#1565C0", "#1976D2")
        self.btn_one.setToolTip("Aplica unpivot apenas na planilha selecionada")
        self.btn_one.clicked.connect(self._run_one)
        self.btn_all = _mkbtn("  Ajustar Todos", "fa5s.forward", "#2E7D32", "#388E3C")
        self.btn_all.setToolTip("Aplica unpivot em todas as planilhas")
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
        self.schema_list.clear()
        try:
            rows = self.db.conn.execute("""
                SELECT DISTINCT s.schema_hash, a.nome_arquivo, s.nome_sheet, s.qtd_linhas
                FROM sheets s JOIN arquivos a ON s.arquivo_id = a.id
                WHERE s.schema_hash IS NOT NULL
                ORDER BY s.ultimo_hash_modificado DESC
            """).fetchall()
            for r in rows:
                txt = f"{r['nome_arquivo']}  ›  {r['nome_sheet']}  ({r['qtd_linhas']} linhas)"
                item = QListWidgetItem(txt)
                item.setData(Qt.UserRole, r["schema_hash"])
                item.setToolTip(f"Arquivo: {r['nome_arquivo']}\nPlanilha: {r['nome_sheet']}\nLinhas: {r['qtd_linhas']}")
                self.schema_list.addItem(item)
        except Exception as e:
            self.log.append(f"Erro: {e}")

    def _run_one(self):
        item = self.schema_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Aviso", "Selecione uma planilha na lista.")
            return
        hid = item.data(Qt.UserRole)
        self.lock_controls(True)
        QMessageBox.information(self, "Informação", f"Transformando schema {hid[:12]}...")
        self._exec_worker(TransformWorker(self._db_path(), hid))

    def _run_all(self):
        self.lock_controls(True)
        QMessageBox.information(self, "Informação", "Transformando todas as planilhas...")
        self._exec_worker(TransformWorker(self._db_path()))

    def lock_controls(self, locked: bool):
        self.btn_one.setEnabled(not locked)
        self.btn_all.setEnabled(not locked)
        self.schema_list.setEnabled(not locked)

    def _on_log(self, text): self.log.append(text)

    def _on_progress(self, value, text):
        self.progress.setValue(value)
        self.progress.setFormat(f"{value}%" if text else f"{value}%")

    def _on_finished(self, ok):
        self.progress.setValue(100 if ok else 0)
        self.lock_controls(False)
        self._populate()
        if ok:
            self.log.append("\n✅ Transformação concluída!")
            registrar_operacao("ajustar", "Transformação concluída", "ok")


# ─────────────────────────────────────────────
#  Exportar
# ─────────────────────────────────────────────
EXPORT_DIR_DEFAULT = str(Path.home() / "planilha_bi_db" / "exports")

# ── Queries para re-pivot (voltar ao formato largo original) ──

_ARQUIVOS_SQL = """
    SELECT DISTINCT da.id as arq_id, da.nome_arquivo
    FROM fact_dados f
    JOIN dim_arquivo da ON f.arquivo_id = da.id
    ORDER BY da.nome_arquivo
"""

_SHEETS_POR_ARQUIVO_SQL = """
    SELECT DISTINCT f.sheet_name
    FROM fact_dados f
    WHERE f.arquivo_id = ?
    ORDER BY f.sheet_name
"""

_COLUNAS_SQL = """
    SELECT DISTINCT dc.nome_coluna_original
    FROM fact_dados f
    JOIN dim_coluna dc ON f.coluna_id = dc.id
    WHERE f.arquivo_id = ? AND f.sheet_name = ?
    ORDER BY dc.nome_coluna_original
"""

_VALORES_SQL = """
    SELECT f.linha_origem, dc.nome_coluna_original,
           COALESCE(f.valor_numerico, f.valor_texto) as valor
    FROM fact_dados f
    JOIN dim_coluna dc ON f.coluna_id = dc.id
    WHERE f.arquivo_id = ? AND f.sheet_name = ?
    ORDER BY f.linha_origem, dc.nome_coluna_original
"""


class ExportPage(BasePage):
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Exportar Dados")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #E0E0E0;")
        layout.addWidget(title)

        sub = QLabel("Uma planilha corrigida por arquivo original. Sem códigos internos, datas dd/mm/yyyy.")
        sub.setStyleSheet("color: #78909C; font-size: 12px; margin-bottom: 16px;")
        layout.addWidget(sub)

        out_row, self.out_edit, self.out_btn = self._path_input(EXPORT_DIR_DEFAULT, "fa5s.folder-open")
        self.out_edit.setText(EXPORT_DIR_DEFAULT)
        self.out_edit.setToolTip("Pasta onde os arquivos serão salvos")
        self.out_btn.setToolTip("Selecionar pasta de destino")
        self.out_btn.clicked.connect(self._browse_out)
        layout.addLayout(out_row)

        fmt_card = QFrame()
        fmt_card.setStyleSheet("""
            QFrame { background-color: #1a1a2e; border: 1px solid #2a2a4e;
                     border-radius: 10px; padding: 16px; margin: 8px 0; }
        """)
        fmtl = QVBoxLayout(fmt_card)
        fl1 = QHBoxLayout()
        lbl_fmt = QLabel("Formato de saída")
        lbl_fmt.setStyleSheet("color: #90CAF9; font-size: 13px; font-weight: bold;")
        fl1.addWidget(lbl_fmt)
        fl1.addStretch()
        fmtl.addLayout(fl1)

        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(["xlsx  (Excel padrão)", "xlsb  (Excel binário)", "csv  (texto)", "parquet  (colunar)"])
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
        self.fmt_combo.setToolTip("xlsx = Excel padrão  |  xlsb = Excel binário  |  csv = texto  |  parquet = colunar")
        fmtl.addWidget(self.fmt_combo)

        self.lbl_sheets = QLabel("Carregando planilhas...")
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
        self.sheet_list.setToolTip("Planilhas disponíveis para exportação")
        layout.addWidget(self.sheet_list)

        self.btn_export = _mkbtn("  Exportar Todas", "fa5s.file-export", "#2E7D32", "#388E3C")
        self.btn_export.setToolTip("Gera um arquivo por planilha original, sem IDs, datas dd/mm/yyyy")
        self.btn_export.setMinimumHeight(50)
        self.btn_export.clicked.connect(self._run_export)
        layout.addWidget(self.btn_export)

        self.progress = self._progress()
        layout.addWidget(self.progress)

        self.log = self._log_area()
        layout.addWidget(self.log, stretch=1)

    def refresh(self):
        self._list_arquivos()

    @staticmethod
    def _arquivos_id_para_raw(self, c, dim_arq_id: int) -> int | None:
        """Mapeia dim_arquivo.id → arquivos.id para queries em raw_data."""
        row = c.execute("SELECT caminho_completo FROM dim_arquivo WHERE id = ?", (dim_arq_id,)).fetchone()
        if not row:
            return None
        try:
            return int(row["caminho_completo"].replace("db://", ""))
        except (ValueError, AttributeError):
            return None

    def _list_arquivos(self):
        self.sheet_list.clear()
        try:
            c = self.db.conn.cursor()
            arquivos = c.execute(_ARQUIVOS_SQL).fetchall()
            if not arquivos:
                self.lbl_sheets.setText("Nenhum dado. Importe e transforme primeiro.")
                return
            total_geral = 0
            total_items = 0
            for arq in arquivos:
                dim_id = arq["arq_id"]
                _arp = c.execute("SELECT caminho_completo FROM dim_arquivo WHERE id = ?", (dim_id,)).fetchone()
                orig_id = int(_arp["caminho_completo"].replace("db://", "")) if _arp else None

                # Sheets com dados corrigidos (fact_dados)
                fact_sheets = c.execute("SELECT DISTINCT sheet_name FROM fact_dados WHERE arquivo_id = ?", (dim_id,)).fetchall()

                # Sheets normais (só raw_data, sem fact_dados) — usa orig_id para raw_data
                raw_sheets = []
                if orig_id is not None:
                    raw_sheets = c.execute("""
                        SELECT DISTINCT s.nome_sheet FROM raw_data rd
                        JOIN sheets s ON rd.sheet_id = s.id
                        WHERE rd.arquivo_id = ?
                        EXCEPT
                        SELECT DISTINCT f.sheet_name FROM fact_dados f WHERE f.arquivo_id = ?
                    """, (orig_id, dim_id)).fetchall()

                for s in fact_sheets:
                    cnt = c.execute("SELECT COUNT(*) as t FROM fact_dados WHERE arquivo_id = ? AND sheet_name = ?",
                                    (dim_id, s["sheet_name"])).fetchone()
                    qtd = cnt["t"]
                    total_geral += qtd
                    label = f"{arq['nome_arquivo']}  ›  {s['sheet_name']}  ({qtd} linhas) ✓ corrigida"
                    item = QListWidgetItem(label)
                    item.setData(Qt.UserRole, ("fact", dim_id, s["sheet_name"], arq["nome_arquivo"]))
                    item.setToolTip("Planilha corrigida (invertida → normalizada)")
                    self.sheet_list.addItem(item)
                    total_items += 1

                for s in raw_sheets:
                    cnt = c.execute("SELECT COUNT(*) as t FROM raw_data rd WHERE rd.arquivo_id = ? AND rd.sheet_id = (SELECT id FROM sheets WHERE arquivo_id = ? AND nome_sheet = ?)",
                                    (orig_id, orig_id, s["nome_sheet"])).fetchone()
                    qtd = cnt["t"]
                    total_geral += qtd
                    label = f"{arq['nome_arquivo']}  ›  {s['nome_sheet']}  ({qtd} linhas) — original"
                    item = QListWidgetItem(label)
                    item.setData(Qt.UserRole, ("raw", dim_id, s["nome_sheet"], arq["nome_arquivo"], orig_id))
                    item.setToolTip("Planilha já no formato correto")
                    self.sheet_list.addItem(item)
                    total_items += 1

            self.lbl_sheets.setText(f"{total_items} planilha(s) · {total_geral} linhas no total")
        except Exception as e:
            self.lbl_sheets.setText(f"Erro: {e}")
            import traceback
            self.lbl_sheets.setToolTip(traceback.format_exc())

    def _browse_out(self):
        path = QFileDialog.getExistingDirectory(self, "Pasta de destino")
        if path:
            self.out_edit.setText(path)

    def _fmt_key(self) -> str:
        raw = self.fmt_combo.currentText()
        if "xlsx" in raw: return "xlsx"
        if "xlsb" in raw: return "xlsb"
        if "csv" in raw: return "csv"
        return "parquet"

    @staticmethod
    def _formatar_data_col(nome: str) -> str:
        """Converte '2025-01' para 'jan/25', mantém outros nomes."""
        import re
        m = re.match(r"(\d{4})-(\d{2})$", nome)
        if m:
            ano, mes = m.groups()
            meses = ["", "jan", "fev", "mar", "abr", "mai", "jun",
                     "jul", "ago", "set", "out", "nov", "dez"]
            return f"{meses[int(mes)]}/{ano[2:]}"
        return nome

    def _build_corrected(self, valores: list) -> tuple:
        """Constrói o formato corrigido.
        - Tabelas invertidas (datas como colunas): [entidades, Data, Valor]
        - Tabelas normais: mantém estrutura original (pass-through)."""
        from collections import OrderedDict
        import re

        col_set = OrderedDict()
        for row in valores:
            col_set[row["nome_coluna_original"]] = True

        colunas_entidade = []
        colunas_data_raw = []
        for col in col_set:
            if re.match(r"\d{4}-\d{2}$", col):
                colunas_data_raw.append(col)
            else:
                colunas_entidade.append(col)

        mapa = {(r["linha_origem"], r["nome_coluna_original"]): r["valor"] for r in valores}
        todas_linhas = sorted(set(r["linha_origem"] for r in valores))

        if not colunas_data_raw:
            # Tabela NORMAL: mantém estrutura original
            cabecalho = colunas_entidade
            linhas = [cabecalho]
            for ln in todas_linhas:
                row = [str(mapa.get((ln, c), "")) for c in colunas_entidade]
                linhas.append(row)
            return cabecalho, linhas

        # Tabela INVERTIDA: corrige para [entidades, Data, Valor]
        cabecalho = colunas_entidade + ["Data", "Valor"]
        linhas = [cabecalho]
        for ln in todas_linhas:
            ent_vals = [str(mapa.get((ln, c), "")) for c in colunas_entidade]
            for col_data in colunas_data_raw:
                dt_fmt = ExportPage._formatar_data_col(col_data)
                val = mapa.get((ln, col_data), "")
                if val is not None and str(val).strip():
                    linhas.append(ent_vals + [dt_fmt, str(val)])
        return cabecalho, linhas

    @staticmethod
    def _merge_tables_side_by_side(subs: list) -> tuple | None:
        """Agrupa múltiplas tabelas corrigidas lado a lado, separadas por colunas em branco.
        Cada tabela mantém sua própria estrutura [entidades, Data, Valor].
        subs = [(sheet_name, colunas, linhas), ...]
        Retorna (colunas_combinadas, linhas_combinadas)."""
        if not subs:
            return None
        return ExportPage._stack_side_by_side(subs)

    @staticmethod
    def _stack_side_by_side(subs: list, colunas_sep: int = 3) -> tuple | None:
        """Empilha múltiplas tabelas lado a lado com N colunas vazias entre elas."""
        if not subs:
            return None

        all_data = []
        max_data_rows = 0
        for _, _, linhas in subs:
            data = linhas[1:] if len(linhas) > 1 else []
            all_data.append((linhas[0] if linhas else [], data))
            max_data_rows = max(max_data_rows, len(data))

        combined_cols = []
        combined_rows = [[] for _ in range(max_data_rows)]

        for idx, (header, data) in enumerate(all_data):
            if idx > 0:
                for _ in range(colunas_sep):
                    combined_cols.append("")
                    for ri in range(max_data_rows):
                        combined_rows[ri].append("")

            combined_cols.extend(header)
            for ri in range(max_data_rows):
                if ri < len(data):
                    combined_rows[ri].extend(data[ri])
                else:
                    combined_rows[ri].extend([""] * len(header))

        return combined_cols, combined_rows

    def _build_raw_table(self, cursor, raw_arquivo_id: int, sheet_name: str) -> tuple:
        """Reconstrói tabela original de raw_data para planilhas normais (pass-through).
        raw_arquivo_id é o id da tabela arquivos (não dim_arquivo)."""
        import json
        rows = cursor.execute("""
            SELECT rd.row_data FROM raw_data rd
            JOIN sheets s ON rd.sheet_id = s.id
            WHERE rd.arquivo_id = ? AND s.nome_sheet = ?
            ORDER BY rd.linha_id
        """, (raw_arquivo_id, sheet_name)).fetchall()
        if not rows:
            return [], []
        first = json.loads(rows[0]["row_data"])
        colunas = list(first.keys())
        data = [colunas]
        for r in rows:
            row_data = json.loads(r["row_data"])
            data.append([str(row_data.get(c, "")) for c in colunas])
        return colunas, data

    def _run_export(self):
        import json, re
        from collections import defaultdict
        dest = Path(self.out_edit.text().strip())
        if not dest.exists():
            try:
                dest.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Não foi possível criar: {dest}")
                return

        fmt = self._fmt_key()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        c = self.db.conn.cursor()
        arquivos = c.execute(_ARQUIVOS_SQL).fetchall()

        if not arquivos:
            QMessageBox.information(self, "Informação", "Nenhum dado para exportar.")
            return

        self.log.append(f"\nExportando no formato {fmt.upper()}...")
        self.lock_controls(True)
        self.progress.setValue(0)
        exported = 0

        for i, arq in enumerate(arquivos):
            groups_by_file = []
            # Mapeia dim_arquivo.id → arquivos.id para raw_data
            _arp = c.execute("SELECT caminho_completo FROM dim_arquivo WHERE id = ?", (arq["arq_id"],)).fetchone()
            arq_id_db = int(_arp["caminho_completo"].replace("db://", "")) if _arp else None

            fact_sheets = c.execute("SELECT DISTINCT sheet_name FROM fact_dados WHERE arquivo_id = ?", (arq["arq_id"],)).fetchall()

            # Sheets normais (raw_data) — consulta pelo id original
            raw_sheets = []
            if arq_id_db is not None:
                raw_sheets = c.execute("""
                    SELECT DISTINCT s.nome_sheet FROM raw_data rd
                    JOIN sheets s ON rd.sheet_id = s.id
                    WHERE rd.arquivo_id = ?
                """, (arq_id_db,)).fetchall()

            fact_names = {s["sheet_name"] for s in fact_sheets}

            # --- Processar sheets corrigidas (fact_dados) ---
            regulares = {}
            sub_agrupadas = defaultdict(list)
            for s in fact_sheets:
                valores = c.execute(_VALORES_SQL, (arq["arq_id"], s["sheet_name"])).fetchall()
                if not valores:
                    continue
                col, lin = self._build_corrected(valores)
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
                    merged = ExportPage._stack_side_by_side(subs)
                    if merged:
                        groups_by_file.append(("fact", base, merged[0], merged[1]))

            # --- Processar sheets normais (raw_data pass-through) ---
            for s in raw_sheets:
                if s["nome_sheet"] in fact_names:
                    continue  # já processada pelo fact_dados
                col, lin = self._build_raw_table(c, arq_id_db, s["nome_sheet"])
                if col:
                    groups_by_file.append(("raw", s["nome_sheet"], col, lin))

            if not groups_by_file:
                continue

            name_base = arq["nome_arquivo"].replace(".xlsx", "").replace(".xlsb", "").replace(".csv", "").replace(".parquet", "")
            safe_name = name_base.replace(" ", "_").replace("/", "-")[:40]
            fname = f"{safe_name}_corrigida_{ts}.{fmt}"
            fpath = dest / fname

            grupos = [(nome, col, lin) for _, nome, col, lin in groups_by_file]

            try:
                if fmt == "csv":
                    for s_name, scol, srows in grupos:
                        sf = f"{safe_name}_{s_name}_corrigida_{ts}.csv"
                        sp = dest / sf
                        self._export_csv_wide(sp, scol, srows)
                        self.log.append(f"  {sf}  ({sp.stat().st_size/1024:.1f} KB)")
                        exported += 1
                elif fmt == "parquet":
                    for s_name, scol, srows in grupos:
                        sf = f"{safe_name}_{s_name}_corrigida_{ts}.parquet"
                        sp = dest / sf
                        self._export_parquet_wide(sp, scol, srows)
                        self.log.append(f"  {sf}  ({sp.stat().st_size/1024:.1f} KB)")
                        exported += 1
                elif fmt == "xlsb":
                    ok = self._export_xlsb_wide(fpath, grupos)
                    if not ok:
                        fpath = fpath.with_suffix(".xlsx")
                        self._export_xlsx_wide(fpath, grupos)
                    sz = fpath.stat().st_size
                    sz_str = f"{sz/1048576:.1f} MB" if sz > 1048576 else f"{sz/1024:.1f} KB"
                    self.log.append(f"  {fname}  ({sz_str}, {len(grupos)} aba(s))")
                    exported += 1
                else:
                    self._export_xlsx_wide(fpath, grupos)
                    sz = fpath.stat().st_size
                    sz_str = f"{sz/1048576:.1f} MB" if sz > 1048576 else f"{sz/1024:.1f} KB"
                    self.log.append(f"  {fname}  ({sz_str}, {len(grupos)} aba(s))")
                    exported += 1

            except Exception as e:
                self.log.append(f"  ✖ {fname}: {e}")
                import traceback
                self.log.append(traceback.format_exc())

            self.progress.setValue(int((i + 1) / len(arquivos) * 100))

        self.progress.setValue(100)
        self.log.append(f"\n✅ {exported} arquivo(s) gerado(s) em {dest}/")
        registrar_operacao("exportar", f"{exported} arquivo(s) exportado(s)", "ok")

        try:
            import subprocess
            subprocess.Popen(["explorer", str(dest)])
        except Exception: pass

        self.lock_controls(False)

    # ── Writers: formato largo (colunas + linhas) ─────────────────────

    def _format_xlsx_ws(self, ws, colunas: list[str], linhas: list):
        """Aplica formatação padronizada + dados a uma planilha."""
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        hf = Font(name="Segoe UI", bold=True, color="FFFFFF", size=11)
        hfill = PatternFill(start_color="1A237E", end_color="1A237E", fill_type="solid")
        ha = Alignment(horizontal="center", vertical="center")
        bdr = Border(left=Side(style="thin"), right=Side(style="thin"),
                     top=Side(style="thin"), bottom=Side(style="thin"))
        for ci, col in enumerate(colunas, 1):
            cell = ws.cell(row=1, column=ci, value=col)
            cell.font = hf; cell.fill = hfill; cell.alignment = ha; cell.border = bdr
        ws.freeze_panes = "A2"
        df = Font(name="Segoe UI", size=10)
        af = PatternFill(start_color="F5F5F5", end_color="F5F5F5", fill_type="solid")
        for ri, row in enumerate(linhas[1:], start=2):  # pula cabeçalho
            for ci, val in enumerate(row, 1):
                cell = ws.cell(row=ri, column=ci, value=val if val is not None else "")
                cell.font = df; cell.border = bdr
                if ri % 2 == 0: cell.fill = af
        for ci in range(1, len(colunas) + 1):
            col_val = str(colunas[ci - 1] or "")
            if col_val.strip() == "":
                # Coluna separadora: mínimo possível
                ws.column_dimensions[ws.cell(row=1, column=ci).column_letter].width = 1.5
            else:
                ml = len(col_val)
                for ri in range(2, min(len(linhas), 200)):
                    v = ws.cell(row=ri, column=ci).value
                    if v: ml = max(ml, min(len(str(v)), 40))
                ws.column_dimensions[ws.cell(row=1, column=ci).column_letter].width = ml + 3

    def _export_xlsx_wide(self, path, grupos: list):
        """grupos = [(nome_aba, colunas, linhas), ...]"""
        from openpyxl import Workbook
        wb = Workbook()
        wb.remove(wb.active)
        for s_name, colunas, linhas in grupos:
            ws = wb.create_sheet(title=s_name[:31])
            self._format_xlsx_ws(ws, colunas, linhas)
        wb.save(str(path))

    def _export_xlsb_wide(self, path, grupos: list) -> bool:
        try:
            import win32com.client as win32
            excel = win32.gencache.EnsureDispatch("Excel.Application")
            excel.DisplayAlerts = False
            wb = excel.Workbooks.Add()
            while wb.Worksheets.Count > 1:
                wb.Worksheets(2).Delete()
            for idx, (s_name, colunas, linhas) in enumerate(grupos):
                ws = wb.Worksheets(1) if idx == 0 else wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
                ws.Name = s_name[:31]
                for j, col in enumerate(colunas, 1):
                    c = ws.Cells(1, j); c.Value = col; c.Font.Bold = True
                    c.Interior.Color = 0x1A237E; c.Font.Color = 0xFFFFFF
                for i, row in enumerate(linhas[1:], 2):
                    for j, val in enumerate(row, 1):
                        ws.Cells(i, j).Value = val if val is not None else ""
                ws.Columns.AutoFit()
            wb.SaveAs(str(path), FileFormat=50)
            wb.Close(); excel.Quit()
            return True
        except Exception:
            return False

    def _export_csv_wide(self, path, colunas: list[str], linhas: list):
        import csv
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            for row in linhas:
                w.writerow([str(v) if v is not None else "" for v in row])

    def _export_parquet_wide(self, path, colunas: list[str], linhas: list):
        import pyarrow as pa, pyarrow.parquet as pq
        arrays = {colunas[i]: [] for i in range(len(colunas))}
        for row in linhas[1:]:
            for i, c in enumerate(colunas):
                arrays[c].append(str(row[i]) if row[i] is not None else "")
        pq.write_table(pa.table(arrays), str(path))

    def lock_controls(self, locked: bool):
        self.btn_export.setEnabled(not locked)
        self.out_btn.setEnabled(not locked)
        self.out_edit.setReadOnly(locked)

    def _on_log(self, text): self.log.append(text)
    def _on_progress(self, value, text): self.progress.setValue(value)
    def _on_error(self, msg):
        self.log.append(f"\n✖ {msg}")
        self.lock_controls(False)
        registrar_operacao("exportar", "Erro na exportação", "erro")
        QMessageBox.critical(self, "Erro", msg)


# ─────────────────────────────────────────────
#  Configurações
# ─────────────────────────────────────────────
class SettingsPage(BasePage):
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Configurações")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #E0E0E0;")
        layout.addWidget(title)
        layout.addSpacing(12)

        # Database info
        grp_db = QGroupBox("Banco de Dados")
        grp_db.setStyleSheet("""
            QGroupBox { color: #90CAF9; font-size: 13px; font-weight: bold;
                        border: 1px solid #2a2a4e; border-radius: 8px;
                        margin-top: 12px; padding: 16px; }
        """)
        dbl = QVBoxLayout(grp_db)
        dbp = QLabel(f"Caminho: {self.db.db_path}")
        dbp.setStyleSheet("color: #B0BEC5; font-size: 12px;")
        dbp.setWordWrap(True)
        dbp.setToolTip("Localização do arquivo SQLite")
        dbl.addWidget(dbp)

        sz = "?"
        try: sz = f"{Path(self.db.db_path).stat().st_size / 1024:.1f} KB"
        except: pass
        dbl.addWidget(QLabel(f"Tamanho: {sz}", styleSheet="color: #B0BEC5; font-size: 12px;"))

        btn_bkup = _mkbtn("  Gerenciar Backups", "fa5s.archive", "#F57F17", "#F9A825")
        btn_bkup.setToolTip("Listar, restaurar ou excluir backups")
        btn_bkup.clicked.connect(self._show_backups)
        dbl.addWidget(btn_bkup)
        layout.addWidget(grp_db)

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
        btn_restore = _mkbtn("  Restaurar", "fa5s.undo", "#E65100", "#EF6C00")
        btn_restore.setToolTip("Substitui o banco atual pelo backup selecionado (útil para recuperação)")
        btn_restore.clicked.connect(self._restore)
        lbl_auto = QLabel("Backups antigos (>30 dias) são removidos automaticamente na limpeza.")
        lbl_auto.setStyleSheet("color: #546E7A; font-size: 11px;")
        bk_actions.addWidget(btn_restore)
        bk_actions.addWidget(lbl_auto)
        bk_actions.addStretch()
        layout.addLayout(bk_actions)

        # Maintenance
        grp_mnt = QGroupBox("Manutenção e Limpeza")
        grp_mnt.setStyleSheet("""
            QGroupBox { color: #90CAF9; font-size: 13px; font-weight: bold;
                        border: 1px solid #2a2a4e; border-radius: 8px;
                        margin-top: 12px; padding: 16px; }
        """)
        mntl = QVBoxLayout(grp_mnt)
        self.cleanup_info = QLabel("Clique em 'Analisar' para ver o que pode ser otimizado.")
        self.cleanup_info.setStyleSheet("color: #B0BEC5; font-size: 12px;")
        self.cleanup_info.setWordWrap(True)
        mntl.addWidget(self.cleanup_info)
        mnt_actions = QHBoxLayout()
        btn_analyze = _mkbtn("  Analisar", "fa5s.stethoscope", "#546E7A", "#607D8B")
        btn_analyze.setToolTip("Verifica o banco e mostra quanto espaço pode ser recuperado")
        btn_analyze.clicked.connect(self._analyze_db)
        btn_clean = _mkbtn("  Limpar e Otimizar", "fa5s.broom", "#2E7D32", "#388E3C")
        btn_clean.setToolTip("Remove dados órfãos, duplicatas e backups antigos. Executa VACUUM.")
        btn_clean.clicked.connect(self._run_cleanup)
        mnt_actions.addWidget(btn_analyze)
        mnt_actions.addWidget(btn_clean)
        mnt_actions.addStretch()
        mntl.addLayout(mnt_actions)
        layout.addWidget(grp_mnt)

        # Export config
        grp_exp = QGroupBox("Exportação Padrão")
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
        self.exp_path_edit.setToolTip("Pasta padrão para exportação de dados")
        expl.addWidget(QLabel("Pasta de exportação:", styleSheet="color: #B0BEC5; font-size: 12px;"))
        expl.addWidget(self.exp_path_edit)
        layout.addWidget(grp_exp)

        layout.addStretch()

    def _refresh_backups(self):
        self.bk_list.clear()
        bm = BackupManager(self._db_path())
        for b in bm.listar_backups():
            item = QListWidgetItem(f"{b['nome']}  ({b['tamanho_kb']} KB)")
            item.setData(Qt.UserRole, b["caminho"])
            item.setToolTip(f"Criado: {b['data'][:19]}")
            self.bk_list.addItem(item)

    def _show_backups(self): self._refresh_backups()

    def _restore(self):
        item = self.bk_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Aviso", "Selecione um backup na lista.")
            return
        path = item.data(Qt.UserRole)
        confirm = QMessageBox.question(self, "Restaurar",
            "Isso substituirá o banco atual. Continuar?",
            QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            bm = BackupManager(self._db_path())
            if bm.restaurar_backup(path):
                QMessageBox.information(self, "Sucesso", "Restaurado. Reinicie.")
            else:
                QMessageBox.critical(self, "Erro", "Falha ao restaurar.")

    def _analyze_db(self):
        try:
            dc = DatabaseCleanup(self._db_path())
            diag = dc.diagnostic()
            raw = diag["raw_orfao"]; audit = diag["audit_total"]
            dup = diag["duplicatas"]; size = diag["tamanho_atual_kb"]
            lines = [
                f"Tamanho: {size:.1f} KB",
                f"Dados brutos órfãos: {raw}",
                f"Registros de auditoria: {audit}",
                f"Duplicatas: {dup}",
            ]
            if raw > 0 or dup > 0:
                lines.append("Recomenda-se limpeza.")
                self.cleanup_info.setText("\n".join(lines))
                self.cleanup_info.setStyleSheet("color: #FFB74D; font-size: 12px;")
            else:
                lines.append("Banco saudável.")
                self.cleanup_info.setText("\n".join(lines))
                self.cleanup_info.setStyleSheet("color: #81C784; font-size: 12px;")
        except Exception as e:
            self.cleanup_info.setText(f"Erro: {e}")
            self.cleanup_info.setStyleSheet("color: #EF5350; font-size: 12px;")

    def _run_cleanup(self):
        confirm = QMessageBox.question(self, "Limpeza",
            "Remover dados brutos já transformados, duplicatas e backups antigos?",
            QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes: return
        self.cleanup_info.setText("Limpando...")
        try:
            dc = DatabaseCleanup(self._db_path())
            stats = dc.run_cleanup()
            lines = [
                f"Brutos removidos: {stats['removidos_raw']}",
                f"Auditoria limpa: {stats['removidos_audit']}",
                f"Duplicatas: {stats['removidos_dup']}",
                f"Backups excluídos: {stats['backups_excluidos']}",
                f"Tamanho: {stats['tamanho_antes_kb']} → {stats['tamanho_depois_kb']} KB",
                f"Economia: {stats['economia_kb']} KB",
            ]
            self.cleanup_info.setText("\n".join(lines))
            self.cleanup_info.setStyleSheet("color: #81C784; font-size: 12px; font-weight: bold;")
            QMessageBox.information(self, "Sucesso", f"Limpeza concluída! {stats['economia_kb']} KB recuperados.")
            registrar_operacao("limpeza", f"Limpeza: {stats['economia_kb']} KB recuperados", "ok")
        except Exception as e:
            self.cleanup_info.setText(f"Erro: {e}")
            QMessageBox.critical(self, "Erro", str(e))
