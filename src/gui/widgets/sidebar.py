import getpass
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Signal, QSize
from PySide6.QtGui import QFont, QPainter, QColor, QBrush, QPen, QLinearGradient, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QFrame, QFileDialog
)

from src.localization import _ as _tr, on_language_change

_PAGINAS = [
    ("dashboard", "fa5s.home", "Dashboard"),
    ("importar", "fa5s.file-import", "Import"),
    ("ajustar", "fa5s.sync-alt", "Adjust"),
    ("exportar", "fa5s.file-export", "Export"),
    ("settings", "fa5s.cog", "Settings"),
]

_PAGINAS_TRANSLATE_KEYS = {
    "dashboard": "Dashboard",
    "importar": "Import",
    "ajustar": "Adjust",
    "exportar": "Export",
    "settings": "Settings",
}


class AvatarWidget(QWidget):
    def __init__(self, nome: str, parent=None):
        super().__init__(parent)
        self.nome = nome
        self.iniciais = self._extrair_iniciais(nome)
        self.setFixedSize(38, 38)
        self.setToolTip(_tr("User: {name}").format(name=nome))

    def _extrair_iniciais(self, nome: str) -> str:
        partes = nome.strip().split()
        if len(partes) >= 2:
            return (partes[0][0] + partes[-1][0]).upper()
        return (nome[:2]).upper() if nome else "??"

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, 38, 38)
        grad.setColorAt(0, QColor("#42A5F5"))
        grad.setColorAt(1, QColor("#1E88E5"))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor("#1565C0"), 2))
        p.drawEllipse(1, 1, 36, 36)
        p.setPen(QColor("white"))
        font = QFont("Segoe UI", 11, QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, self.iniciais)
        p.end()


class LogoTarget(QWidget):
    """Drop zone for company logo."""
    logo_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)
        self.setAcceptDrops(True)
        self._pixmap = None
        self._path = None
        self.setToolTip(_tr("Drag company logo here"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_saved()

    def _load_saved(self):
        cfg_path = Path.home() / "sheetpilot_db" / "company_logo.txt"
        try:
            if cfg_path.exists():
                path = cfg_path.read_text(encoding="utf-8").strip()
                if Path(path).exists():
                    self._set_logo(path)
        except Exception:
            pass

    def _save_path(self, path: str):
        cfg_path = Path.home() / "sheetpilot_db" / "company_logo.txt"
        try:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(path, encoding="utf-8")
        except Exception:
            pass

    def _set_logo(self, path: str):
        pix = QPixmap(path)
        if not pix.isNull():
            self._pixmap = pix.scaled(180, 52, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
            self._path = path
            self._save_path(path)
            self.logo_changed.emit(path)
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._pixmap and not self._pixmap.isNull():
            x = (self.width() - self._pixmap.width()) // 2
            y = (self.height() - self._pixmap.height()) // 2
            p.drawPixmap(x, y, self._pixmap)
        else:
            p.setPen(QPen(QColor("#2a2a4e"), 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(255, 255, 255, 5))
            p.drawRoundedRect(4, 4, self.width() - 8, self.height() - 8, 8, 8)
            icon = qta.icon("fa5s.building", color="#455A64")
            pix = icon.pixmap(24, 24)
            p.drawPixmap((self.width() - 24) // 2, (self.height() - 24) // 2 - 6, pix)
            p.setPen(QColor("#455A64"))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(self.rect().adjusted(0, 12, 0, 0), Qt.AlignCenter, _tr("Logo"))
        p.end()

    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(self, _tr("Select Logo"), "",
                                              _tr("Images (*.png *.jpg *.jpeg *.svg *.bmp)"))
        if path:
            self._set_logo(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".bmp")):
                self._set_logo(path)
                break


class SidebarButton(QPushButton):
    def __init__(self, page_id, icon_name, text_key, parent=None):
        super().__init__(parent)
        self.page_id = page_id
        self._icon_name = icon_name
        self._text_key = text_key
        self._icon = qta.icon(icon_name, color="#90A4AE")
        self._icon_active = qta.icon(icon_name, color="white")
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self._expanded = True
        self._active = False
        self._show_text()

    def set_theme_colors(self, text_color="#90A4AE", active_color="white"):
        self._icon = qta.icon(self._icon_name, color=text_color)
        self._icon_active = qta.icon(self._icon_name, color=active_color)
        self._show_text()

    def retranslate(self):
        text = _tr(self._text_key)
        self.setToolTip(text)
        self._show_text()

    def _show_text(self):
        icon = self._icon_active if self._active else self._icon
        text = _tr(self._text_key)
        if self._expanded:
            self.setIcon(icon)
            self.setIconSize(QSize(20, 20))
            self.setText(f" {text}")
        else:
            self.setIcon(icon)
            self.setIconSize(QSize(22, 22))
            self.setText("")
        self.setFont(QFont("Segoe UI", 11))
        self._apply_style()

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self._show_text()

    def set_active(self, active: bool):
        self._active = active
        self._show_text()

    def _apply_style(self):
        if self._active:
            self.setStyleSheet("""
                SidebarButton {
                    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #1565C0, stop:1 #1976D2);
                    color: white;
                    border: none;
                    border-radius: 10px;
                    padding: 8px 12px;
                    font-weight: 600;
                    text-align: left;
                }
                SidebarButton:hover {
                    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #1976D2, stop:1 #1E88E5);
                }
            """)
        else:
            self.setStyleSheet("""
                SidebarButton {
                    background-color: transparent;
                    color: #90A4AE;
                    border: none;
                    border-radius: 10px;
                    padding: 8px 12px;
                    text-align: left;
                }
                SidebarButton:hover {
                    background-color: rgba(255,255,255,0.07);
                    color: #E0E0E0;
                }
            """)


class Sidebar(QWidget):
    page_changed = Signal(str)

    EXPANDED_WIDTH = 200
    COLLAPSED_WIDTH = 56
    ANIM_DURATION = 280

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = True
        self._buttons: list[SidebarButton] = []
        self._setup_ui()
        self.setFixedWidth(self.EXPANDED_WIDTH)
        self.setMinimumWidth(self.EXPANDED_WIDTH)
        self.setMaximumWidth(self.EXPANDED_WIDTH)
        on_language_change(lambda: self.retranslate_ui())

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 12)
        layout.setSpacing(2)

        # Toggle — starts expanded → show X
        t_btn = QPushButton()
        t_btn.setIcon(qta.icon("fa5s.times", color="#90CAF9"))
        t_btn.setIconSize(QSize(20, 20))
        t_btn.setFixedHeight(40)
        t_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        t_btn.setToolTip(_tr("Collapse menu"))
        t_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent; border: none; border-radius: 8px;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.10);
            }
        """)
        t_btn.clicked.connect(self._toggle)
        self._toggle_btn = t_btn
        layout.addWidget(t_btn)

        # Logo zone
        self.logo_widget = LogoTarget()
        layout.addWidget(self.logo_widget)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #252a4a;")
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        layout.addSpacing(4)

        # Nav buttons
        for pid, icon, text_key in _PAGINAS:
            btn = SidebarButton(pid, icon, text_key)
            btn.clicked.connect(lambda checked=False, p=pid: self._on_page_clicked(p))
            btn.retranslate()
            self._buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch()

        # User section
        self.avatar_frame = QWidget()
        av_layout = QVBoxLayout(self.avatar_frame)
        av_layout.setContentsMargins(8, 4, 8, 8)
        av_layout.setSpacing(4)
        av_layout.setAlignment(Qt.AlignCenter)

        username = getpass.getuser()
        self.avatar = AvatarWidget(username)
        av_layout.addWidget(self.avatar, 0, Qt.AlignCenter)

        self.user_label = QLabel(username)
        self.user_label.setAlignment(Qt.AlignCenter)
        self.user_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.user_label.setStyleSheet("color: #90A4AE; border: none;")
        self.user_label.setToolTip(_tr("User: {name}").format(name=username))
        av_layout.addWidget(self.user_label)

        self.version_label = QLabel("v0.1.0")
        self.version_label.setAlignment(Qt.AlignCenter)
        self.version_label.setFont(QFont("Segoe UI", 9))
        self.version_label.setStyleSheet("color: #455A64; border: none;")
        self.version_label.setToolTip("SheetPilot")
        av_layout.addWidget(self.version_label)

        layout.addWidget(self.avatar_frame)

    def update_theme_colors(self, is_dark: bool):
        bg = "#161b2e" if is_dark else "#f0f2f5"
        border = "#252a4a" if is_dark else "#d0d4dc"
        text = "#90A4AE" if is_dark else "#607D8B"
        self.setStyleSheet(f"""
            Sidebar {{
                background-color: {bg};
                border-right: 1px solid {border};
            }}
        """)
        for btn in self._buttons:
            btn.set_theme_colors(text_color=text, active_color="white")

    def _on_page_clicked(self, page_id):
        for btn in self._buttons:
            btn.set_active(btn.page_id == page_id)
        self.page_changed.emit(page_id)

    def _toggle(self):
        self._expanded = not self._expanded
        target = self.EXPANDED_WIDTH if self._expanded else self.COLLAPSED_WIDTH

        self.anim = QPropertyAnimation(self, b"maximumWidth")
        self.anim.setDuration(self.ANIM_DURATION)
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(target)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.start()

        self.anim_min = QPropertyAnimation(self, b"minimumWidth")
        self.anim_min.setDuration(self.ANIM_DURATION)
        self.anim_min.setStartValue(self.width())
        self.anim_min.setEndValue(target)
        self.anim_min.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim_min.start()

        # Swap icon: bars when collapsed, X when expanded
        self._toggle_btn.setIcon(qta.icon(
            "fa5s.times" if self._expanded else "fa5s.bars", color="#90CAF9"
        ))
        self._toggle_btn.setToolTip(
            _tr("Collapse menu") if self._expanded else _tr("Expand menu")
        )

        visible = self._expanded
        self.logo_widget.setVisible(visible)
        for btn in self._buttons:
            btn.set_expanded(visible)
        self.user_label.setVisible(visible)
        self.version_label.setVisible(visible)

    def retranslate_ui(self):
        for btn in self._buttons:
            btn.retranslate()
        self._toggle_btn.setToolTip(
            _tr("Collapse menu") if self._expanded else _tr("Expand menu")
        )

    def set_active_page(self, page_id: str):
        for btn in self._buttons:
            btn.set_active(btn.page_id == page_id)
