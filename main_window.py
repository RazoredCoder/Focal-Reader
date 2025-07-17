import os
import sys
import configparser
import nltk
import azure.cognitiveservices.speech as speechsdk
from appdirs import AppDirs
import fitz  # Import for PyMuPDF
import re # Import regular expressions for finding numbers

from PySide6.QtCore import QObject, QThread, Signal, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QTextCursor, QColor, QTextCharFormat
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTextEdit, 
                               QHBoxLayout, QPushButton, QFileDialog, QMessageBox)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from settings_dialog import SettingsDialog

# =================================================================================
# ENHANCED TEXT EDIT WIDGET
# =================================================================================
class InteractiveTextEdit(QTextEdit):
    clicked_at_pos = Signal(int)
    hovered_at_pos = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        cursor = self.cursorForPosition(event.pos())
        position = cursor.position()
        self.clicked_at_pos.emit(position)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        cursor = self.cursorForPosition(event.pos())
        position = cursor.position()
        self.hovered_at_pos.emit(position)

# =================================================================================
# WORKER CLASS (Stable Version)
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
        
        self.current_file_path = None
        self.current_start_page = None
        
        self.sentences = []
        self.sentence_spans = [] 
        self.paragraph_sentence_map = []
        self.current_sentence_index = 0
        
        self.playback_highlighter = None
        self.hover_highlighter = None
        self._setup_formats()
        
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.buffer = QBuffer()
        
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        
        self._setup_config_and_nlp()
        self._setup_ui()
        self.load_and_set_credentials()

    def _setup_formats(self):
        self.playback_format = QTextCharFormat()
        self.playback_format.setBackground(QColor("#FFF9C4")) 

        self.hover_format = QTextCharFormat()
        self.hover_format.setBackground(QColor("#F5F5F5"))

    def _setup_config_and_nlp(self):
        APP_NAME = "FocalReader"
        APP_AUTHOR = "Maksymilian Wicinski"
        dirs = AppDirs(APP_NAME, APP_AUTHOR)
        self.config_path = os.path.join(dirs.user_config_dir, "config.ini")
        
        self.tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')
        custom_abbreviations = {'etc', 'mr', 'mrs', 'ms', 'dr', 'prof', 'rev', 'capt', 'sgt', 'col', 'gen', 'vs', 'no', 'e.g', 'i.e', 'et al'}
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

        self.text_area = InteractiveTextEdit()
        self.text_area.setReadOnly(True)
        self.layout.addWidget(self.text_area)

        controls_container = QWidget()
        controls_layout = QHBoxLayout(controls_container)
        self.layout.addWidget(controls_container)

        self.prev_paragraph_button = QPushButton("<< Prev Para")
        self.prev_sentence_button = QPushButton("< Prev Sent")
        self.play_button = QPushButton("Play")
        self.next_sentence_button = QPushButton("Next Sent >")
        self.next_paragraph_button = QPushButton("Next Para >>")
        self.stop_button = QPushButton("Stop")
        self.load_button = QPushButton("Load File")
        self.fix_start_button = QPushButton("Fix Start")

        controls_layout.addWidget(self.load_button)
        controls_layout.addWidget(self.fix_start_button)
        controls_layout.addWidget(self.prev_paragraph_button)
        controls_layout.addWidget(self.prev_sentence_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.next_sentence_button)
        controls_layout.addWidget(self.next_paragraph_button)
        controls_layout.addWidget(self.stop_button)

        setting_action.triggered.connect(self.open_settings)
        self.play_button.clicked.connect(self.play_tts)
        self.stop_button.clicked.connect(self.stop_tts)
        self.load_button.clicked.connect(self.open_file)
        self.prev_sentence_button.clicked.connect(self.previous_sentence)
        self.next_sentence_button.clicked.connect(self.next_sentence)
        self.prev_paragraph_button.clicked.connect(self.previous_paragraph)
        self.next_paragraph_button.clicked.connect(self.next_paragraph)
        self.fix_start_button.clicked.connect(self.load_previous_page)
        
        self.text_area.clicked_at_pos.connect(self.on_text_area_clicked)
        self.text_area.hovered_at_pos.connect(self.on_text_area_hovered)

        self.stop_button.setEnabled(False)
        self.prev_sentence_button.setEnabled(False)
        self.next_sentence_button.setEnabled(False)
        self.prev_paragraph_button.setEnabled(False)
        self.next_paragraph_button.setEnabled(False)
        self.fix_start_button.setEnabled(False)

    def _apply_highlight(self, start, end, text_format):
        cursor = self.text_area.textCursor()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, end - start)
        cursor.setCharFormat(text_format)
        return cursor

    def _clear_highlight(self, highlighter):
        if highlighter:
            highlighter.setCharFormat(QTextCharFormat())

    def on_text_area_hovered(self, position):
        if self.playback_state == "PLAYING": return
        self._clear_highlight(self.hover_highlighter)
        for i, (start, end) in enumerate(self.sentence_spans):
            if start <= position < end:
                self.hover_highlighter = self._apply_highlight(start, end, self.hover_format)
                break
    
    def on_text_area_clicked(self, position):
        if not self.sentence_spans: return
        if self.playback_state == "PLAYING": self.stop_tts()

        target_sentence_index = -1
        for i, (start, end) in enumerate(self.sentence_spans):
            if start <= position < end:
                target_sentence_index = i
                break
        
        if target_sentence_index != -1:
            self.current_sentence_index = target_sentence_index
            self.play_tts()

    def previous_sentence(self):
        if not self.sentences: return
        if self.playback_state == "PLAYING": self.stop_tts()
        
        new_index = self.current_sentence_index - 1
        if new_index >= 0:
            self.current_sentence_index = new_index
            self.play_tts()

    def next_sentence(self):
        if not self.sentences: return
        if self.playback_state == "PLAYING": self.stop_tts()

        new_index = self.current_sentence_index + 1
        if new_index < len(self.sentences):
            self.current_sentence_index = new_index
            self.play_tts()

    def previous_paragraph(self):
        if not self.paragraph_sentence_map: return
        if self.playback_state == "PLAYING": self.stop_tts()

        current_para_index = -1
        for i, para_sentences in enumerate(self.paragraph_sentence_map):
            if self.current_sentence_index in para_sentences:
                current_para_index = i
                break
        
        if current_para_index > 0:
            prev_para_sentences = self.paragraph_sentence_map[current_para_index - 1]
            self.current_sentence_index = prev_para_sentences[0]
            self.play_tts()

    def next_paragraph(self):
        if not self.paragraph_sentence_map: return
        if self.playback_state == "PLAYING": self.stop_tts()

        current_para_index = -1
        for i, para_sentences in enumerate(self.paragraph_sentence_map):
            if self.current_sentence_index in para_sentences:
                current_para_index = i
                break
        
        if current_para_index != -1 and current_para_index < len(self.paragraph_sentence_map) - 1:
            next_para_sentences = self.paragraph_sentence_map[current_para_index + 1]
            self.current_sentence_index = next_para_sentences[0]
            self.play_tts()

    def play_tts(self):
        if self.playback_state == "PLAYING": return
        if not self.azure_key or not self.azure_region:
            self.open_settings(); return
        
        if not self.sentences: self._process_text(self.text_area.toPlainText())
        if not self.sentences: return

        self.playback_state = "PLAYING"
        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.prev_sentence_button.setEnabled(True)
        self.next_sentence_button.setEnabled(True)
        self.prev_paragraph_button.setEnabled(True)
        self.next_paragraph_button.setEnabled(True)
        
        self.play_sentence(self.current_sentence_index)

    def play_sentence(self, index):
        if self.playback_state != "PLAYING" or index >= len(self.sentences):
            self.stop_tts(); return

        self.current_sentence_index = index
        text = self.sentences[index]
        
        self._clear_highlight(self.hover_highlighter)
        self._clear_highlight(self.playback_highlighter)
        start, end = self.sentence_spans[index]
        self.playback_highlighter = self._apply_highlight(start, end, self.playback_format)

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
        
        self._clear_highlight(self.playback_highlighter)
        self._clear_highlight(self.hover_highlighter)

        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        
        nav_enabled = True if self.sentences else False
        self.prev_sentence_button.setEnabled(nav_enabled)
        self.next_sentence_button.setEnabled(nav_enabled)
        self.prev_paragraph_button.setEnabled(nav_enabled)
        self.next_paragraph_button.setEnabled(nav_enabled)

    def on_tts_error(self, error_message):
        QMessageBox.critical(self, "An Azure TTS Error Occurred", error_message)
        self.stop_tts()

    def load_previous_page(self):
        if self.current_file_path == None: return
        if self.current_start_page <= 0: return

        new_start_page = self.current_start_page - 1
        doc = fitz.open(self.current_file_path)
        text = self._extract_text_from_pdf(doc, new_start_page)
        self._process_text(text)
        self.current_start_page = new_start_page
    
    def open_file(self):
        if self.playback_state != "STOPPED": self.stop_tts()
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Open File", 
            "", 
            "All Readable Files (*.txt *.pdf);;Text Files (*.txt);;PDF Files (*.pdf)"
        )
        if not file_path:
            return
        
        self.current_file_path = file_path
        
        content = ""
        try:
            if file_path.lower().endswith('.pdf'):
                with fitz.open(file_path) as doc:
                    print(f"PDF has {len(doc)} pages.")
                    self.current_start_page = self._detect_pdf_start_page(doc)
                    content = self._extract_text_from_pdf(doc, self.current_start_page)
                self.fix_start_button.setEnabled(True)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.current_start_page = 0
            self._process_text(content)
        except Exception as e:
            QMessageBox.critical(self, "Error Reading File", f"Could not read the file.\n\nError: {e}")

    def _detect_pdf_start_page(self, doc):
        self.chapter_keywords = ['prologue', 'epilogue', 'chapter', 'appendix', 'afterword', 'interlude', 'side story']
        toc_page_candidates = []
        for page_num in range(min(15, len(doc))):
            page = doc.load_page(page_num)
            link_list = page.get_links()

            print(f"--- Page {page_num + 1} ---")
            for link in link_list:
                link_text = page.get_text("text", clip=link['from'])
                
                print(f"Found a link: {link}")
                print(f"Its link text is {link_text}")

                for keyword in self.chapter_keywords:
                    if keyword.lower() in link_text.lower():
                        print(f"------> This link contains the keyword '{keyword}'.\n\n")
                        toc_page_candidates.append(page_num)
                        break
            
        print(f"================== Table of content page candidates: {toc_page_candidates} =======================")

        true_last_toc_page = -1
        if toc_page_candidates:
            true_last_toc_page = toc_page_candidates[0]

            for i in range(1, len(toc_page_candidates)):
                if toc_page_candidates[i] == toc_page_candidates[i-1] + 1:
                    true_last_toc_page = toc_page_candidates[i]
                else:
                    break

        print(f"================== The real last TOC page is: {true_last_toc_page} =======================")
        return true_last_toc_page + 1

    def _extract_text_from_pdf(self, doc, start_page):
        full_text = []
        page_numbers = {}

        for page_num in range(start_page, len(doc)):
            page = doc.load_page(page_num)
            page_height = page.rect.height
            footer_margin = page_height * 0.90
            
            blocks = page.get_text("blocks")
            for block in blocks:
                if block[6] == 0: 
                    block_y_pos = block[1]
                    block_text = block[4].strip()

                    if block_y_pos > footer_margin:
                        found_numbers = re.findall(r'\d+', block_text)
                        if found_numbers:
                            page_numbers[page_num + 1] = int(found_numbers[0])
                            print(f"Found and skipped footer on page {page_num + 1}: '{block_text}'")
                            continue 
                    
                    full_text.append(block_text)
    
        print(f"Extracted page numbers: {page_numbers}")
        return "\n".join(full_text)            

    def _process_text(self, raw_text):
        print("Processing text...")
        
        self.sentences = []
        self.sentence_spans = []
        self.paragraph_sentence_map = []
        
        if not raw_text:
            self.text_area.setText("")
            self.stop_tts()
            return

        # Part 1: Text Cleaning
        para_break_placeholder = " [PARA_BREAK] "
        
        processed_text = raw_text.replace('\n\n', para_break_placeholder)
        
        for keyword in self.chapter_keywords:
            processed_text = re.sub(r'\n\s*(' + keyword + r'(\s+\d+)?)', rf'{para_break_placeholder}\1', processed_text, flags=re.IGNORECASE)

        raw_sentence_spans = list(self.tokenizer.span_tokenize(processed_text))

        cleaned_paragraphs = []
        current_paragraph_sentences = []

        for i, (start, end) in enumerate(raw_sentence_spans):
            sentence_text = processed_text[start:end]
            unwrapped_sentence = sentence_text.replace('\n', ' ').strip()
            if unwrapped_sentence:
                current_paragraph_sentences.append(unwrapped_sentence)

            is_last_sentence = (i == len(raw_sentence_spans) - 1)
            next_char_is_newline = (end < len(processed_text) and processed_text[end] == '\n')
            
            if (is_last_sentence or next_char_is_newline) and current_paragraph_sentences:
                cleaned_paragraph = " ".join(current_paragraph_sentences)
                cleaned_paragraphs.append(cleaned_paragraph)
                current_paragraph_sentences = []

        final_text = "\n\n".join(cleaned_paragraphs)
        final_text = final_text.replace(para_break_placeholder.strip(), "\n\n")
        self.text_area.setText(final_text)

        # --- Part 2: Analyze the final, clean text to build the navigation maps ---

        full_text_for_analysis = self.text_area.toPlainText()

        # 2a. Get the master list of sentences and their character positions (spans).
        self.sentence_spans = list(self.tokenizer.span_tokenize(full_text_for_analysis))
        self.sentences = [full_text_for_analysis[start:end] for start, end in self.sentence_spans]

        # 2b. Build the paragraph map by checking the text *between* sentences.
        self.paragraph_sentence_map = []
        if not self.sentences:
            print("Processing complete: No sentences found.")
            self.stop_tts()
            return

        current_paragraph_indices = []
        for i, (start, end) in enumerate(self.sentence_spans):
            current_paragraph_indices.append(i)

            is_last_sentence = (i == len(self.sentence_spans) - 1)

            # Define the region of text to check for a paragraph break.
            check_start = end
            check_end = len(full_text_for_analysis)
            if not is_last_sentence:
                # Look only between the end of this sentence and the start of the next one.
                check_end = self.sentence_spans[i + 1][0]
            
            intervening_text = full_text_for_analysis[check_start:check_end]

            # If we find a double newline or it's the last sentence, this paragraph is complete.
            if "\n\n" in intervening_text or is_last_sentence:
                self.paragraph_sentence_map.append(current_paragraph_indices)
                current_paragraph_indices = []

        # --- Finalization ---
        print(f"Processed {len(self.sentences)} sentences in {len(self.paragraph_sentence_map)} paragraphs.")
        self.current_sentence_index = 0
        nav_enabled = bool(self.sentences)
        self.prev_sentence_button.setEnabled(nav_enabled)
        self.next_sentence_button.setEnabled(nav_enabled)
        self.prev_paragraph_button.setEnabled(nav_enabled)
        self.next_paragraph_button.setEnabled(nav_enabled)

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
