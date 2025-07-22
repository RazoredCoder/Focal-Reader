from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QPushButton

class ImageViewerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide() # Hidden by default
        self.setStyleSheet("background-color: rgba(0, 0, 0, 180);")

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)

        self.close_button = QPushButton("✕", self)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setStyleSheet("""
            QPushButton { font-size: 20px; font-weight: bold; color: white; background-color: transparent; border: none; }
            QPushButton:hover { color: #dddddd; }
        """)
        self.close_button.clicked.connect(self.hide)

    def show_image(self, pixmap: QPixmap):
        """Public method to display an image."""
        # First, ensure our size matches the parent window's current size.
        if self.parent():
            self.setGeometry(0, 0, self.parent().width(), self.parent().height())
        
        scaled_pixmap = pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled_pixmap)
        self.image_label.setGeometry(0, 0, self.width(), self.height())
        self.close_button.move(self.width() - 40, 10)
        
        self.raise_()
        self.show()
        
    def keyPressEvent(self, event):
        """Close the viewer when the Escape key is pressed."""
        if event.key() == Qt.Key_Escape:
            self.hide()