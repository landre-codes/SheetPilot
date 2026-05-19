import qtawesome as qta
from PySide6.QtCore import Qt, Signal, QPoint, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton

from src.localization import _, on_language_change


class TitleBar(QWidget):
    MINIMIZE = 0
    MAXIMIZE = 1
    CLOSE = 2

    window_action = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        self._drag_pos = QPoint()
        self.setFixedHeight(40)
        self.setStyleSheet("""
            TitleBar {
                background-color: #0d1117;
                border-bottom: 1px solid #30363d;
            }
        """)
        on_language_change(lambda: self.retranslate_ui())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(4)

        self.icon_label = QLabel()
        self.icon_label.setPixmap(qta.icon("fa5s.database", color="#42A5F5").pixmap(18, 18))
        self.icon_label.setFixedWidth(24)
        self.icon_label.setToolTip("SheetPilot")
        layout.addWidget(self.icon_label)

        self.title_label = QLabel("SheetPilot")
        self.title_label.setStyleSheet("color: #E0E0E0; font-size: 13px; font-weight: 600; letter-spacing: 1.5px;")
        self.title_label.setFont(QFont("Montserrat", 10, QFont.Weight.DemiBold))
        layout.addWidget(self.title_label)

        self.page_label = QLabel()
        self.page_label.setStyleSheet("color: #42A5F5; font-size: 12px; font-weight: 500; padding-left: 8px;")
        layout.addWidget(self.page_label)
        layout.addStretch()

        self.btn_min = QPushButton()
        self._style_btn(self.btn_min, "fa5s.window-minimize", _("Minimize"))
        self.btn_min.clicked.connect(lambda: self.window_action.emit(self.MINIMIZE))
        layout.addWidget(self.btn_min)

        self.btn_max = QPushButton()
        self._style_btn(self.btn_max, "fa5s.window-maximize", _("Maximize"))
        self.btn_max.clicked.connect(lambda: self.window_action.emit(self.MAXIMIZE))
        layout.addWidget(self.btn_max)

        self.btn_close = QPushButton()
        self._style_btn(self.btn_close, "fa5s.times", _("Close"), close=True)
        self.btn_close.clicked.connect(lambda: self.window_action.emit(self.CLOSE))
        layout.addWidget(self.btn_close)

    def _style_btn(self, btn, icon_name, tooltip="", close=False):
        btn.setIcon(qta.icon(icon_name, color="#B0BEC5"))
        btn.setIconSize(QSize(16, 16))
        btn.setFixedSize(36, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        base = """
            QPushButton {
                background-color: transparent; border: none; border-radius: 4px;
            }
            QPushButton:hover { background-color: rgba(255,255,255,0.08); }
        """
        if close:
            base = """
                QPushButton {
                    background-color: transparent; border: none; border-radius: 4px;
                }
                QPushButton:hover { background-color: #F44336; }
            """
        btn.setStyleSheet(base)

    def retranslate_ui(self):
        self.btn_min.setToolTip(_("Minimize"))
        self.btn_max.setToolTip(_("Maximize"))
        self.btn_close.setToolTip(_("Close"))

    def set_page_title(self, title: str):
        self.page_label.setText(f"|  {title}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() == Qt.MouseButton.LeftButton:
            parent = self.parent().window() if self.parent() else None
            if parent:
                delta = event.globalPosition().toPoint() - self._drag_pos
                parent.move(parent.pos() + delta)
                self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.window_action.emit(self.MAXIMIZE)
        event.accept()
