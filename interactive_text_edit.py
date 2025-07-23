from PySide6.QtCore import QObject, QThread, Signal, QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTextBrowser)

class InteractiveTextEdit(QTextBrowser):
    clicked_at_pos = Signal(int)
    hovered_at_pos = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        cursor = self.cursorForPosition(event.pos())
        position = cursor.position()
        self.clicked_at_pos.emit(position)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        cursor = self.cursorForPosition(event.pos())
        position = cursor.position()
        self.hovered_at_pos.emit(position)