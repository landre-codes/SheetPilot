import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QStatusBar, QLabel
)
from qt_material import apply_stylesheet

from src.gui.backup import BackupManager
from src.gui.pages import (
    DashboardPage, ImportPage, TransformPage,
    ExportPage, SettingsPage
)
from src.gui.widgets.sidebar import Sidebar
from src.gui.widgets.titlebar import TitleBar
from src.storage.database import Database

DEFAULT_DB_DIR = Path.home() / "planilha_bi_db"
DEFAULT_DB_PATH = str(DEFAULT_DB_DIR / "pilot.db")

# Win32 constants for native shadow
DWM_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


class MainWindow(QMainWindow):
    def __init__(self, db: Database = None):
        super().__init__()
        self.db_path = DEFAULT_DB_PATH
        self.db = db or self._init_db()
        self._maximized = False
        self._pages = {}

        self.setWindowTitle("Planilha BI Pilot")
        self.setMinimumSize(1024, 680)
        self.resize(1280, 800)

        self._setup_frameless()
        self._setup_ui()
        self._apply_native_shadow()
        self._check_backup()
        self._show_page("dashboard")

    def _init_db(self) -> Database:
        DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
        database = Database(self.db_path)
        database.connect()
        mig_path = Path(__file__).parent.parent.parent / "migrations"
        database.run_migrations(str(mig_path))
        return database

    def _setup_frameless(self):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowMinMaxButtonsHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

    def _apply_native_shadow(self):
        try:
            hwnd = int(self.winId())
            dwmapi = ctypes.windll.dwmapi
            # Enable dark title bar (Windows 10/11)
            attr = ctypes.c_int(2)
            dwmapi.DwmSetWindowAttribute(
                ctypes.wintypes.HWND(hwnd),
                19,  # DWMWA_USE_IMMERSIVE_DARK_MODE
                ctypes.byref(ctypes.c_int(1)),
                ctypes.sizeof(ctypes.c_int(1))
            )
            # Round corners (Windows 11)
            try:
                corner = ctypes.c_int(DWMWCP_ROUND)
                dwmapi.DwmSetWindowAttribute(
                    ctypes.wintypes.HWND(hwnd),
                    DWM_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(corner),
                    ctypes.sizeof(corner)
                )
            except Exception:
                pass
            # Shadow
            margins = ctypes.wintypes.RECT(-1, -1, -1, -1)
            dwmapi.DwmExtendFrameIntoClientArea(
                ctypes.wintypes.HWND(hwnd),
                ctypes.byref(margins)
            )
        except Exception:
            pass

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Custom title bar
        self.title_bar = TitleBar()
        self.title_bar.window_action.connect(self._handle_title_action)
        root_layout.addWidget(self.title_bar)

        # Body: sidebar + content
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.page_changed.connect(self._show_page)
        body_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("""
            QStackedWidget {
                background-color: #0d1117;
            }
            QStackedWidget QScrollBar:vertical {
                background: #161b2e; width: 10px; border: none; border-radius: 5px;
            }
            QStackedWidget QScrollBar::handle:vertical {
                background: #30363d; min-height: 30px; border-radius: 5px;
            }
            QStackedWidget QScrollBar::handle:vertical:hover {
                background: #42A5F5;
            }
            QStackedWidget QScrollBar::add-line:vertical,
            QStackedWidget QScrollBar::sub-line:vertical {
                height: 0; border: none;
            }
            QStackedWidget QScrollBar:horizontal {
                background: #161b2e; height: 10px; border: none; border-radius: 5px;
            }
            QStackedWidget QScrollBar::handle:horizontal {
                background: #30363d; min-width: 30px; border-radius: 5px;
            }
            QStackedWidget QScrollBar::handle:horizontal:hover {
                background: #42A5F5;
            }
            QStackedWidget QScrollBar::add-line:horizontal,
            QStackedWidget QScrollBar::sub-line:horizontal {
                width: 0; border: none;
            }
        """)
        body_layout.addWidget(self.stack, stretch=1)

        root_layout.addWidget(body, stretch=1)

        # Status bar
        self.status = QStatusBar()
        self.status.setFixedHeight(28)
        self.status.setStyleSheet("""
            QStatusBar {
                background-color: #0d1117;
                border-top: 1px solid #30363d;
                color: #607D8B;
                font-size: 11px;
                padding: 2px 12px;
            }
        """)
        self.db_label = QLabel(f"DB: {self.db_path}")
        self.db_label.setStyleSheet("color: #455A64; font-size: 10px;")
        self.db_label.setFont(QFont("Segoe UI", 9))
        self.status.addPermanentWidget(self.db_label)
        root_layout.addWidget(self.status)

        # Build pages
        self._pages["dashboard"] = DashboardPage(self.db)
        self._pages["importar"] = ImportPage(self.db)
        self._pages["ajustar"] = TransformPage(self.db)
        self._pages["exportar"] = ExportPage(self.db)
        self._pages["settings"] = SettingsPage(self.db)

        for pid, page in self._pages.items():
            self.stack.addWidget(page)

    def _handle_title_action(self, action):
        if action == TitleBar.CLOSE:
            self.close()
        elif action == TitleBar.MINIMIZE:
            self.showMinimized()
        elif action == TitleBar.MAXIMIZE:
            self._toggle_maximize()

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _show_page(self, page_id: str):
        page = self._pages.get(page_id)
        if page:
            self.stack.setCurrentWidget(page)
            self.sidebar.set_active_page(page_id)
            if hasattr(page, "refresh"):
                page.refresh()
            title_map = {
                "dashboard": "Dashboard", "importar": "Importar",
                "ajustar": "Ajustar", "exportar": "Exportar",
                "settings": "Configurações"
            }
            self.title_bar.set_page_title(title_map.get(page_id, ""))

    def _check_backup(self):
        bm = BackupManager(self.db_path)
        if bm.precisa_backup():
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "Backup Semanal",
                "Ultimo backup tem mais de 7 dias.\n\nCriar um backup agora?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                path = bm.executar_backup()
                if path:
                    self.status.showMessage(f"Backup: {Path(path).name}", 8000)

    def closeEvent(self, event):
        if self.db:
            self.db.close()
        super().closeEvent(event)


def start_gui(db: Database = None):
    app = QApplication(sys.argv)
    apply_stylesheet(app, theme="dark_blue.xml", invert_secondary=False)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow(db)
    window.show()
    sys.exit(app.exec())
