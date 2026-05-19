from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar

from src.localization import _


class LoadingOverlay(QWidget):
    """Sobreposição semi-transparente com spinner textual e barra de progresso.
    Uso típico:
        overlay = LoadingOverlay(parent=self)
        overlay.show()
        overlay.set_progress(45, "Processando arquivo 3/10...")
    """

    def __init__(self, parent=None, message: str = None):
        super().__init__(parent)
        self._message = message or _("Loading...")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(13, 17, 23, 200);")
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)

        self._spinner = QLabel("⏳")
        self._spinner.setAlignment(Qt.AlignCenter)
        self._spinner.setStyleSheet("font-size: 36px; background: transparent;")
        layout.addWidget(self._spinner)

        self._label = QLabel(message)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "color: #E0E0E0; font-size: 15px; font-weight: 600; background: transparent;"
        )
        layout.addWidget(self._label)

        self._sub = QLabel("")
        self._sub.setAlignment(Qt.AlignCenter)
        self._sub.setStyleSheet(
            "color: #90A4AE; font-size: 12px; background: transparent;"
        )
        layout.addWidget(self._sub)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedWidth(300)
        self._bar.setFixedHeight(6)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("""
            QProgressBar {
                background-color: #30363d; border: none; border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #42A5F5; border-radius: 3px;
            }
        """)
        layout.addWidget(self._bar, 0, Qt.AlignCenter)

    def set_progress(self, value: int, sub_text: str = ""):
        self._bar.setValue(value)
        self._sub.setText(sub_text)

    def set_message(self, message: str):
        self._label.setText(message)

    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            self.resize(self.parent().size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.parent():
            self.resize(self.parent().size())
