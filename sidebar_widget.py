from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton

class SidebarWidget(QWidget):
    # Signals to tell the MainWindow which view to show
    show_toc_requested = Signal()
    show_gallery_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        # Reduced horizontal margins
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(5)
        self.layout.setAlignment(Qt.AlignTop)

        # Create the buttons with the new text
        self.toc_button = QPushButton("|||")
        self.gallery_button = QPushButton("[ ]")
        
        self.toc_button.setToolTip("Table of Contents")
        self.gallery_button.setToolTip("Image Gallery")
        
        # --- THE FIX: Reduced padding and font size ---
        self.setStyleSheet("""
            QPushButton {
                padding: 6px;
                font-size: 12px;
                font-weight: bold;
            }
        """)

        # Add them to the layout
        self.layout.addWidget(self.toc_button)
        self.layout.addWidget(self.gallery_button)

        # Connect button clicks to signals
        self.toc_button.clicked.connect(self.show_toc_requested)
        self.gallery_button.clicked.connect(self.show_gallery_requested)

        # --- THE FIX: Set a narrower fixed width ---
        self.setFixedWidth(35)