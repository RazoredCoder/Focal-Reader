import sys
from PySide6.QtWidgets import QApplication
from main_window import MainWindow
from dotenv import load_dotenv

# --- Start of Logging Setup ---
class Logger(object):
    def __init__(self, filename="debug.log"):
        self.terminal = sys.stdout
        self.log = open(filename, "w", encoding='utf-8')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

sys.stdout = Logger()
sys.stderr = sys.stdout
# --- End of Logging Setup ---

print("--- Starting main.py ---")

try:
    load_dotenv()
    print("1. Environment variables loaded.")

    app = QApplication(sys.argv)
    print("2. QApplication created.")

    window = MainWindow()
    print("4. MainWindow instance created.")

    window.show()
    print("5. MainWindow shown.")

    print("6. Starting event loop (app.exec())...")
    exit_code = app.exec()
    print(f"7. Event loop finished. Exiting with code {exit_code}.")
    sys.exit(exit_code)
except Exception as e:
    print(f"\n--- A FATAL EXCEPTION OCCURRED ---\n")
    import traceback
    traceback.print_exc()
    input("Press Enter to exit...")