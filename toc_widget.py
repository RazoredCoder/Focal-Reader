from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem

class TOCWidget(QWidget):
    # A signal that will be emitted when a user clicks a chapter title.
    # It will carry the anchor name (a string) for the MainWindow to use.
    toc_entry_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.layout = QVBoxLayout(self)
        self.toc_list_widget = QListWidget()
        self.layout.addWidget(self.toc_list_widget)
        
        # Set some basic styling
        self.toc_list_widget.setStyleSheet("""
            QListWidget {
                border: none;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 8px;
            }
            QListWidget::item:hover {
                background-color: #e0e0e0;
            }
            QListWidget::item:selected {
                background-color: #c0c0c0;
                color: black;
            }
        """)

        # Connect the itemClicked signal to our handler method
        self.toc_list_widget.itemClicked.connect(self._on_item_clicked)

    def populate_toc(self, toc_data):
        """
        Clears the current list and populates it with new TOC data.
        'toc_data' is expected to be a list of (title, anchor_name) tuples.
        """
        self.toc_list_widget.clear()
        for title, anchor_name in toc_data:
            item = QListWidgetItem(title)
            # Store the anchor name directly in the item for later retrieval
            item.setData(1, anchor_name) # Using role 1 for custom data
            self.toc_list_widget.addItem(item)
            
    def _on_item_clicked(self, item):
        """
        Retrieves the anchor name from the clicked item and emits the signal.
        """
        anchor_name = item.data(1)
        if anchor_name:
            self.toc_entry_selected.emit(anchor_name)