from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

class ThumbnailWidget(QLabel):
    # A signal that will be emitted when the thumbnail is clicked.
    # It will carry the full-resolution QPixmap object for the viewer.
    clicked = Signal(QPixmap)

    def __init__(self, image_data, parent=None):
        super().__init__(parent)
        
        # Load the raw image data into a QPixmap
        self.full_pixmap = QPixmap()
        self.full_pixmap.loadFromData(image_data)

        # Create a scaled-down version for the thumbnail display
        self.thumbnail_pixmap = self.full_pixmap.scaled(
            150, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        
        self.setPixmap(self.thumbnail_pixmap)
        
        # Set widget properties
        self.setAlignment(Qt.AlignCenter)
        self.setToolTip("Click to view full size")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def mousePressEvent(self, event):
        """Emits the clicked signal with the full-resolution image."""
        self.clicked.emit(self.full_pixmap)
        super().mousePressEvent(event)