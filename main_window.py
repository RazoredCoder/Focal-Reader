from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTextEdit, QHBoxLayout, QPushButton, QFileDialog
import os
import azure.cognitiveservices.speech as speechsdk
import nltk
from settings_dialog import SettingsDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.sentences = []
        self.current_sentence_index = 0
        self.is_paused = False

        custom_abbreviations = {'etc', 'mr', 'mrs', 'ms', 'dr', 'prof', 'rev', 'capt', 'sgt', 'col', 'gen', 'vs', 'no', 'e.g', 'i.e', 'et al'}
        self.tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')
        self.tokenizer._params.abbrev_types.update(custom_abbreviations)

        self.setWindowTitle("Focal Reader")
        self.resize(800,600 )

        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File") # "&"" creates an underlined shortcut
        setting_action = file_menu.addAction("Settings")
        setting_action.triggered.connect(self.open_setting)

        self.container = QWidget()
        self.setCentralWidget(self.container)
        
        self.layout = QVBoxLayout()
        self.container.setLayout(self.layout)

        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.layout.addWidget(self.text_area)

        self.controls_container = QWidget()
        self.controls_layout = QHBoxLayout()
        self.controls_container.setLayout(self.controls_layout)

        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.skip_button = QPushButton("Next Paragraph")
        self.load_button = QPushButton("Load File")

        self.controls_layout.addWidget(self.play_button)
        self.controls_layout.addWidget(self.pause_button)
        self.controls_layout.addWidget(self.skip_button)
        self.controls_layout.addWidget(self.load_button)

        self.layout.addWidget(self.controls_container)

        self.play_button.clicked.connect(self.play_tts)
        self.pause_button.clicked.connect(self.pause_tts)
        self.skip_button.clicked.connect(self.skip_tts)
        self.load_button.clicked.connect(self.open_file)
    
    def open_setting(self):
        dialog = SettingsDialog(self)
        dialog.exec()
    
    def play_tts(self):
        self.full_text = self.text_area.toPlainText()
        self.sentences = self.tokenizer.tokenize(self.full_text)
        self.current_sentence_index = 0
        self.is_paused = False
        print(f"Text split into {len(self.sentences)} sentences.")
        self.speak_current_sentence()
        

    def pause_tts(self):
        print("Pause button clicked!")
    
    def skip_tts(self):
        print("Skip button clicked!")

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Text File", "", "Text Files (*.txt)")

        if file_path:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.text_area.setText(content)
    
    def speak_current_sentence(self):
        self.speech_key = os.getenv("AZURE_SPEECH_KEY")
        self.speech_region = os.getenv("AZURE_SPEECH_REGION")
        self.speech_config = speechsdk.SpeechConfig(subscription=self.speech_key, region=self.speech_region)
        self.speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=self.speech_config)

        self.result = self.speech_synthesizer.speak_text_async(self.sentences[self.current_sentence_index]).get()