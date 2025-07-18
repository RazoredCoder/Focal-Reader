from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QPushButton, QVBoxLayout, QMessageBox, QInputDialog

class EmergencyDialog(QDialog):
    fix_start_requested = Signal()
    new_footer_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Emergency Menu")

        layout = QVBoxLayout()

        self.fix_start_button = QPushButton("Load Previous Page (Fix Start)")
        self.fix_start_button.setToolTip("If the book started too late (e.g., spipped a prologue), click this")

        self.add_custom_footer_button = QPushButton("Add Custom Footer Pattern")
        self.add_custom_footer_button.setToolTip("If a footer is not being removed, you can add its text here.")

        layout.addWidget(self.fix_start_button)
        layout.addWidget(self.add_custom_footer_button)
        self.setLayout(layout)

        self.fix_start_button.clicked.connect(self.request_fix_start)
        self.add_custom_footer_button.clicked.connect(self.request_add_custom_footer)
    
    def request_fix_start(self):
        self.fix_start_requested.emit()
        self.accept()
    
    def request_add_custom_footer(self):
        text, ok = QInputDialog.getText(self, "Add Custom Footer", 
                                        "Enter the exact text of the footer to remove:")
        
        if ok and text:
            self.new_footer_requested.emit(text)
            QMessageBox.information(self, "Success", "New footer patterm added. The document will be reprocessed.")
            self.accept()