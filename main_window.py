from settings_dialog import SettingsDialog

from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTextEdit, QHBoxLayout, QPushButton, QFileDialog, QMessageBox
from PySide6.QtCore import QObject, QThread, Signal

import os
from appdirs import AppDirs
import configparser

import nltk
import azure.cognitiveservices.speech as speechsdk

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread = None

        APP_NAME = "FocalReader"
        APP_AUTOR = "Maksymilian Wicinski"
        dirs = AppDirs(APP_NAME, APP_AUTOR)
        self.config_path = os.path.join(dirs.user_config_dir, "config.ini")

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

        self.azure_key = None
        self.azure_region = None
        self.load_and_set_credentials()
    
    def open_setting(self):
        dialog = SettingsDialog(self)
        
        key, region = self.load_settings()
        if key and region:
            dialog.set_values(key, region)

        if dialog.exec():
            new_key, new_region = dialog.get_values()
            self.save_settings(new_key, new_region)
            print("Setting saved!")

    def save_settings(self, key, region):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

        config = configparser.ConfigParser()
        config['Azure'] = {
            'SpeechKey': key,
            'SpeechRegion': region
        }
        with open(self.config_path, 'w') as configfile:
            config.write(configfile)
        self.load_and_set_credentials()
    
    def load_settings(self):
        config = configparser.ConfigParser()
        if os.path.exists(self.config_path):
            config.read(self.config_path)
            key = config.get('Azure', 'SpeechKey', fallback=None)
            region = config.get('Azure', 'SpeechRegion', fallback=None)
            return key, region
        return None, None

    def load_and_set_credentials(self):
        self.azure_key, self.azure_region = self.load_settings()
        print("Credentials loaded.")

    def play_tts(self):
        if not self.azure_key or not self.azure_region:
            self.open_setting()
            return
        
        full_text = self.text_area.toPlainText()
        if not full_text:
            print("Text area is empty.")
            return
        
        self.sentences = self.tokenizer.tokenize(full_text)
        self.current_sentence_index = 0

        if not self.sentences:
            print("No sentences found in the text.")
            return
        
        text_to_speak = self.sentences[self.current_sentence_index]

        self.thread = QThread()
        self.worker = Worker(self.azure_key, self.azure_region, text_to_speak)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(self.on_tts_error)

        self.thread.start()

        self.play_button.setEnabled(False)
        self.thread.finished.connect(lambda: self.play_button.setEnabled(True))

    def on_tts_error(self, error_message):
        error_dialog = QMessageBox()
        error_dialog.setIcon(QMessageBox.Icon.Critical)
        error_dialog.setText("An Azure TTS Error Occurred")
        error_dialog.setInformativeText(error_message)
        error_dialog.setWindowTitle("Error")
        error_dialog.exec()

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


class Worker(QObject):
    finished = Signal()
    error = Signal(str)
    
    def __init__(self, key, region, text):
        super().__init__()
        self.key = key
        self.region = region
        self.text = text

    def run(self):
        error_message = None
        
        try:
            if not self.key or not self.region:
                raise ValueError("Azure credentials are not set.")
            
            speech_config = speechsdk.SpeechConfig(subscription=self.key, region=self.region)
            speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config)
            result = speech_synthesizer.speak_text_async(self.text).get()
        
            if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
                if result.reason == speechsdk.ResultReason.Canceled:
                    error_message = "Authentication failed. Please check your Azure credentials in File > Settings."
                else:    
                    error_message = f"Speech synthesis failed. Reason: {result.reason}"
                

        except Exception as e:
            error_message = str(e)
        
        finally:
            if error_message:
                self.error.emit(error_message)
            
            self.finished.emit()