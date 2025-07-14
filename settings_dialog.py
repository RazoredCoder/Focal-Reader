from PySide6.QtWidgets import QDialog, QLineEdit, QPushButton, QFormLayout, QHBoxLayout, QVBoxLayout

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self. setWindowTitle("Settings")

        main_layout = QVBoxLayout()
        form_layout = QFormLayout()
        button_layout = QHBoxLayout()

        self.key_input = QLineEdit()
        self.region_input = QLineEdit()
        form_layout.addRow("Azure Speech Key:", self.key_input)
        form_layout.addRow("Azure Speech Region:", self.region_input)

        self.save_button = QPushButton("Save")
        self.cancel_button = QPushButton("Cancel")
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)

        main_layout.addLayout(form_layout)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
