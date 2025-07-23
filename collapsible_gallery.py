from PySide6.QtCore import Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolBox

from image_gallery_widget import ImageGalleryWidget

class CollapsibleGallery(QWidget):
    thumbnail_clicked = Signal(str, QPixmap)

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.tool_box = QToolBox()
        self.tool_box.setStyleSheet("QToolBox::tab { font-weight: bold; }")
        self.layout.addWidget(self.tool_box)
        
        self.thumbnail_map = {} # Maps {image_id: ThumbnailWidget}
        self.highlighted_thumbnail = None
        # NEW: A map to find which gallery a thumbnail belongs to
        self.thumbnail_to_gallery_map = {}

    def populate(self, grouped_images, toc_data):
        while self.tool_box.count() > 0:
            widget = self.tool_box.widget(0)
            self.tool_box.removeItem(0)
            widget.deleteLater()
        
        self.thumbnail_map = {}
        self.highlighted_thumbnail = None
        self.thumbnail_to_gallery_map = {}

        def create_gallery_section(image_list):
            gallery = ImageGalleryWidget()
            new_thumbnails = gallery.populate_gallery(image_list)
            for thumb in new_thumbnails:
                self.thumbnail_map[thumb.image_id] = thumb
                # Store a reference to the gallery this thumb belongs to
                self.thumbnail_to_gallery_map[thumb] = gallery
            gallery.thumbnail_clicked.connect(self.thumbnail_clicked)
            return gallery

        cover_images = grouped_images.get("cover", [])
        if cover_images:
            self.tool_box.addItem(create_gallery_section(cover_images), "Cover Images")

        chapter_images = grouped_images.get("chapters", [])
        for i, chapter_image_list in enumerate(chapter_images):
            if chapter_image_list:
                chapter_title = f"Chapter {i+1} Images"
                if i < len(toc_data):
                    chapter_title = toc_data[i][0]
                self.tool_box.addItem(create_gallery_section(chapter_image_list), chapter_title)

        ending_images = grouped_images.get("ending", [])
        if ending_images:
            self.tool_box.addItem(create_gallery_section(ending_images), "Ending Images")
            
    def highlight_thumbnail(self, image_id):
        self.unhighlight_all()
        
        thumbnail = self.thumbnail_map.get(image_id)
        if not thumbnail:
            print(f"Warning: Thumbnail with ID '{image_id}' not found.")
            return

        # --- THE FIX ---
        # Find the gallery widget this thumbnail belongs to using our map
        parent_gallery = self.thumbnail_to_gallery_map.get(thumbnail)
        
        # Find which toolbox tab this gallery is in and switch to it
        if parent_gallery:
            for i in range(self.tool_box.count()):
                if self.tool_box.widget(i) == parent_gallery:
                    self.tool_box.setCurrentIndex(i)
                    break
        
        thumbnail.highlight()
        self.highlighted_thumbnail = thumbnail

    def unhighlight_all(self):
        if self.highlighted_thumbnail:
            self.highlighted_thumbnail.unhighlight()
            self.highlighted_thumbnail = None