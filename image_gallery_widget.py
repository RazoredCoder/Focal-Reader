from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QLabel

from thumbnail_widget import ThumbnailWidget

class ImageGalleryWidget(QWidget):
    thumbnail_clicked = Signal(QPixmap)

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.gallery_container = QWidget()
        # --- REVERTED to a simple, reliable QVBoxLayout ---
        self.gallery_layout = QVBoxLayout(self.gallery_container)
        self.gallery_layout.setAlignment(Qt.AlignTop) # Thumbnails will stack from the top
        self.gallery_layout.setSpacing(10)

        self.scroll_area.setWidget(self.gallery_container)
        self.main_layout.addWidget(self.scroll_area)

    def populate_gallery(self, image_data_list):
        """
        Clears the gallery and populates it with new thumbnails.
        """
        # A robust way to clear all widgets from the layout
        while self.gallery_layout.count():
            item = self.gallery_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not image_data_list:
            self.gallery_layout.addWidget(QLabel("No insert images found."))
            return

        for image_data in image_data_list:
            thumbnail = ThumbnailWidget(image_data)
            thumbnail.clicked.connect(self.thumbnail_clicked)
            self.gallery_layout.addWidget(thumbnail)