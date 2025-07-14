from main_window import MainWindow

from PySide6.QtWidgets import QApplication

import sys
from dotenv import load_dotenv

load_dotenv()

qapp = QApplication(sys.argv)

mainWindow = MainWindow()
mainWindow.show()

qapp.exec()
