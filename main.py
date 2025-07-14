from PySide6.QtWidgets import QApplication
from main_window import MainWindow
import sys
from dotenv import load_dotenv

load_dotenv()

qapp = QApplication(sys.argv)

mainWindow = MainWindow()
mainWindow.show()

qapp.exec()

# This is a test comment