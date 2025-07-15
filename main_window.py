import os
import sys
import configparser
import nltk
import azure.cognitiveservices.speech as speechsdk
from appdirs import AppDirs

from PySide6.QtCore import QObject, QThread, Signal, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTextEdit, 
                               QHBoxLayout, QPushButton, QFileDialog, QMessageBox)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from settings_dialog import SettingsDialog

# =================================================================================
# CLICKABLE TEXT EDIT WIDGET
# We subclass QTextEdit to add our own custom click behaviour
# =================================================================================
class ClickableTextEdit(QTextEdit):
    clicked_at_pos = Signal(int)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        cursor = self.cursorForPosition(event.pos())
        position = cursor.position()

        print(f"Mouse clicked at character position {position}")
        self.clicked_at_pos.emit(position)


# =================================================================================
# WORKER CLASS (Stable Version)
# This worker's only job is to fetch audio data for one sentence.
# =================================================================================
class Worker(QObject):
    finished = Signal(QByteArray)
    error = Signal(str)

    def __init__(self, key, region, text_to_speak):
        super().__init__()
        self.key = key
        self.region = region
        self.text = text_to_speak

    def run(self):
        try:
            if not self.key or not self.region:
                raise ValueError("Azure credentials are not set.")
            
            speech_config = speechsdk.SpeechConfig(subscription=self.key, region=self.region)
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
            result = synthesizer.speak_text_async(self.text).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                self.finished.emit(QByteArray(result.audio_data))
                return
            
            error_message = ""
            if result.reason == speechsdk.ResultReason.Canceled:
                error_message = "Authentication failed. Please check your Azure credentials and network connection."
            else:
                error_message = f"Speech synthesis failed. Reason: {result.reason}"
            
            self.error.emit(error_message)

        except Exception as e:
            self.error.emit(str(e))

# =================================================================================
# MAIN WINDOW CLASS (Stable Version)
# =================================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.worker = None
        
        self.playback_state = "STOPPED"
        self.sentences = []
        self.current_sentence_index = 0
        
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.buffer = QBuffer()
        
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        
        self._setup_config_and_nlp()
        self._setup_ui()
        self.load_and_set_credentials()

    def _setup_config_and_nlp(self):
        APP_NAME = "FocalReader"
        APP_AUTHOR = "Maksymilian Wicinski"
        dirs = AppDirs(APP_NAME, APP_AUTHOR)
        self.config_path = os.path.join(dirs.user_config_dir, "config.ini")
        
        custom_abbreviations = {'etc', 'mr', 'mrs', 'ms', 'dr', 'prof', 'rev', 'capt', 'sgt', 'col', 'gen', 'vs', 'no', 'e.g', 'i.e', 'et al'}
        self.tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')
        self.tokenizer._params.abbrev_types.update(custom_abbreviations)

    def _setup_ui(self):
        self.setWindowTitle("Focal Reader")
        self.resize(800, 600)

        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        setting_action = file_menu.addAction("Settings")

        self.container = QWidget()
        self.setCentralWidget(self.container)
        self.layout = QVBoxLayout()
        self.container.setLayout(self.layout)

        self.text_area = ClickableTextEdit()
        self.text_area.setReadOnly(True)
        self.layout.addWidget(self.text_area)

        controls_container = QWidget()
        controls_layout = QHBoxLayout(controls_container)
        self.layout.addWidget(controls_container)

        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.load_button = QPushButton("Load File")

        controls_layout.addWidget(self.load_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.stop_button)

        setting_action.triggered.connect(self.open_settings)
        self.play_button.clicked.connect(self.play_tts)
        self.stop_button.clicked.connect(self.stop_tts)
        self.load_button.clicked.connect(self.open_file)

        self.text_area.clicked_at_pos.connect(self.on_text_area_clicked)

        self.stop_button.setEnabled(False)

    def on_text_area_clicked(self, position):
        print(f"MainWindow received click at postion: {position}")

        if self.playback_state == "PLAYING":
            self.stop_tts()

        full_text = self.text_area.toPlainText()
        if not full_text: return
        self.sentences = self.tokenizer.tokenize(full_text)

        char_count = 0
        target_sentence_index = -1
        for i, sentence in enumerate(self.sentences):
            # The length of the sentence plus a space for separation
            sentence_lenght = len(sentence) + 1
            if char_count <= position < char_count + sentence_lenght:
                target_sentence_index = i
                break
            char_count += sentence_lenght
        
        if target_sentence_index != -1:
            print(f"Clicked position belongs to sentence index: {target_sentence_index}")

            self.current_sentence_index = target_sentence_index
            self.play_tts()
        else:
            print("Could not determine sentence for clicked position.")

    def play_tts(self):
        if self.playback_state == "PLAYING":
            return

        if not self.azure_key or not self.azure_region:
            self.open_settings(); return
        
        if not self.sentences:
            full_text = self.text_area.toPlainText()
            if not full_text: return
            self.sentences = self.tokenizer.tokenize(full_text)
            self.current_sentence_index = 0

        if not self.sentences: return

        self.playback_state = "PLAYING"
        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        
        self.play_sentence(self.current_sentence_index)

    def play_sentence(self, index):
        if self.playback_state != "PLAYING" or index >= len(self.sentences):
            self.stop_tts()
            return

        self.current_sentence_index = index
        text = self.sentences[index]
        print(f"Fetching audio for sentence {index + 1}...")

        self.thread = QThread(parent=self)
        self.worker = Worker(self.azure_key, self.azure_region, text)
        self.worker.moveToThread(self.thread)

        self.worker.error.connect(self.on_tts_error)
        self.worker.finished.connect(self.play_audio_data)

        self.thread.started.connect(self.worker.run)
        self.thread.start()

    def play_audio_data(self, audio_data):
        if not audio_data or self.playback_state != "PLAYING":
            self.on_media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)
            return

        print(f"Playing audio for sentence {self.current_sentence_index + 1}...")
        
        self.player.stop()
        self.player.setSourceDevice(None)

        self.buffer.close()
        self.buffer.setData(audio_data)
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        
        self.player.setSourceDevice(self.buffer)
        self.player.play()

    def on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self.playback_state == "PLAYING":
            next_index = self.current_sentence_index + 1
            if next_index < len(self.sentences):
                self.play_sentence(next_index)
            else:
                print("All sentences finished.")
                self.stop_tts()

    def stop_tts(self):
        if self.playback_state == "STOPPED": return
            
        self.playback_state = "STOPPED"
        self.player.stop()
        
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()
        
        self.thread = None
        self.worker = None

        # self.sentences = []
        # self.current_sentence_index = 0
        
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def on_tts_error(self, error_message):
        QMessageBox.critical(self, "An Azure TTS Error Occurred", error_message)
        self.stop_tts()

    def open_file(self):
        if self.playback_state != "STOPPED": self.stop_tts()
        
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Text File", "", "Text Files (*.txt)")
        if file_path:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.text_area.setText(content)
            self.sentences = []

    def open_settings(self):
        dialog = SettingsDialog(self)
        key, region = self.load_settings()
        if key and region:
            dialog.set_values(key, region)
        if dialog.exec():
            new_key, new_region = dialog.get_values()
            self.save_settings(new_key, new_region)

    def save_settings(self, key, region):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        config = configparser.ConfigParser()
        config['Azure'] = {'SpeechKey': key, 'SpeechRegion': region}
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
