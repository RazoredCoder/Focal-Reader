from PySide6.QtCore import Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolBox

from image_gallery_widget import ImageGalleryWidget

class CollapsibleGallery(QWidget):
    # This signal will pass the click event up from the child galleries to the MainWindow
    thumbnail_clicked = Signal(QPixmap)

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # The QToolBox widget provides the collapsible "accordion" functionality
        self.tool_box = QToolBox()
        self.tool_box.setStyleSheet("QToolBox::tab { font-weight: bold; }")
        
        self.layout.addWidget(self.tool_box)

    def populate(self, grouped_images, toc_data):
        """
        Clears the old galleries and creates a new collapsible section for each image group.
        """
        # Clear any existing widgets from the toolbox
        while self.tool_box.count() > 0:
            self.tool_box.removeItem(0)

        # --- Create "Cover Images" section ---
        cover_images = grouped_images.get("cover", [])
        if cover_images:
            cover_gallery = ImageGalleryWidget()
            cover_gallery.populate_gallery(cover_images)
            cover_gallery.thumbnail_clicked.connect(self.thumbnail_clicked)
            self.tool_box.addItem(cover_gallery, "Cover Images")

        # --- Create a section for each chapter that has images ---
        chapter_images = grouped_images.get("chapters", [])
        for i, chapter_image_list in enumerate(chapter_images):
            if chapter_image_list:
                # Get the corresponding chapter title from the TOC data
                # We need a fallback title in case the TOC is shorter
                chapter_title = f"Chapter {i+1} Images"
                if i < len(toc_data):
                    chapter_title = toc_data[i][0] # Get the title from the (title, anchor) tuple

                chapter_gallery = ImageGalleryWidget()
                chapter_gallery.populate_gallery(chapter_image_list)
                chapter_gallery.thumbnail_clicked.connect(self.thumbnail_clicked)
                self.tool_box.addItem(chapter_gallery, chapter_title)

        # --- Create "Ending Images" section ---
        ending_images = grouped_images.get("ending", [])
        if ending_images:
            ending_gallery = ImageGalleryWidget()
            ending_gallery.populate_gallery(ending_images)
            ending_gallery.thumbnail_clicked.connect(self.thumbnail_clicked)
            self.tool_box.addItem(ending_gallery, "Ending Images")
