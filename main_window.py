import os
import sys
import configparser
import nltk
import re
from appdirs import AppDirs

from PySide6.QtCore import QObject, QThread, Signal, QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QTextCursor, QColor, QTextCharFormat, QBrush
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTextEdit, 
                               QHBoxLayout, QPushButton, QFileDialog, QMessageBox, QSplitter)

# Local imports
from settings_dialog import SettingsDialog
from emergency_dialog import EmergencyDialog
from pdf_handler import PDFHandler
from epub_handler import EpubHandler
from tts_handler import TTSHandler
from toc_widget import TOCWidget

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
# MAIN WINDOW CLASS
# =================================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.playback_state = "STOPPED"
        self.current_file_path, self.current_start_page = None, None
        self.toc_destinations = []

        self.footer_patterns = [re.compile(r'^Page\s+\d+', re.IGNORECASE), re.compile(r'^\d+\s*\|\s*P\s*a\s*g\s*e', re.IGNORECASE)]
        self.chapter_keywords = ['prologue', 'epilogue', 'chapter', 'appendix', 'afterword', 'interlude', 'side story']
        
        # --- Instantiate Handlers ---
        self.pdf_handler = PDFHandler(self.chapter_keywords, self.footer_patterns)
        self.epub_handler = EpubHandler(self.chapter_keywords)
        self.tts_handler = TTSHandler()

        self.sentences, self.sentence_spans, self.paragraph_sentence_map = [], [], []
        self.current_sentence_index = 0
        self.playback_highlighter, self.hover_highlighter = None, None
        
        self._setup_formats()
        self._setup_config_and_nlp()
        self._setup_ui()
        self.load_and_set_credentials()

        # --- Connect to TTSHandler signals ---
        self.tts_handler.playback_started.connect(self._on_playback_started)
        self.tts_handler.playback_finished.connect(self._on_sentence_finished)
        self.tts_handler.playback_stopped.connect(self._on_playback_stopped)
        self.tts_handler.error_occurred.connect(self.on_tts_error)

    def _setup_ui(self):
        self.setWindowTitle("Focal Reader")
        self.resize(800, 600)
        
        # --- Menus ---
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        setting_action = file_menu.addAction("Settings")
        
        # --- Main Layout Structure ---
        self.container = QWidget()
        self.main_layout = QVBoxLayout(self.container)

        # --- Two-Column Splitter ---
        self.splitter = QSplitter(Qt.Horizontal)
        
        self.text_area = InteractiveTextEdit()
        self.text_area.setReadOnly(True)
        
        self.right_panel = QWidget()
        self.right_panel_layout = QVBoxLayout(self.right_panel)
        self.right_panel.setStyleSheet("background-color: #fafafa;") 
        
        self.toc_widget = TOCWidget()
        self.right_panel_layout.addWidget(self.toc_widget)

        self.splitter.addWidget(self.text_area)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([600, 200])
        self.splitter.setStretchFactor(0, 1)

        self.main_layout.addWidget(self.splitter, 1)
        
        # --- Control Buttons ---
        controls_container = QWidget()
        controls_layout = QHBoxLayout(controls_container)
        
        self.load_button = QPushButton("Load File")
        self.emergency_button = QPushButton("Emergency Menu")
        self.prev_paragraph_button = QPushButton("<< Prev Para")
        self.prev_sentence_button = QPushButton("< Prev Sent")
        self.play_button = QPushButton("Play")
        self.next_sentence_button = QPushButton("Next Sent >")
        self.next_paragraph_button = QPushButton("Next Para >>")
        self.stop_button = QPushButton("Stop")
        
        controls_layout.addWidget(self.load_button)
        controls_layout.addWidget(self.emergency_button)
        controls_layout.addWidget(self.prev_paragraph_button)
        controls_layout.addWidget(self.prev_sentence_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.next_sentence_button)
        controls_layout.addWidget(self.next_paragraph_button)
        controls_layout.addWidget(self.stop_button)
        
        self.main_layout.addWidget(controls_container, 0)
        self.setCentralWidget(self.container)

        # --- Connections ---
        self.toc_widget.toc_entry_selected.connect(self.jump_to_anchor)
        setting_action.triggered.connect(self.open_settings)
        self.play_button.clicked.connect(self.play_tts)
        self.stop_button.clicked.connect(self.stop_tts)
        self.load_button.clicked.connect(self.open_file)
        self.prev_sentence_button.clicked.connect(self.previous_sentence)
        self.next_sentence_button.clicked.connect(self.next_sentence)
        self.prev_paragraph_button.clicked.connect(self.previous_paragraph)
        self.next_paragraph_button.clicked.connect(self.next_paragraph)
        self.emergency_button.clicked.connect(self.open_emergency_menu)
        self.text_area.clicked_at_pos.connect(self.on_text_area_clicked)
        self.text_area.hovered_at_pos.connect(self.on_text_area_hovered)
        
        # Initial button states
        self.stop_button.setEnabled(False)
        self.set_nav_buttons_enabled(False)
        self.emergency_button.setEnabled(False)


    def _setup_formats(self):
        self.playback_format = QTextCharFormat()
        self.playback_format.setBackground(QColor("#FFF9C4")) 

        self.hover_format = QTextCharFormat()
        self.hover_format.setBackground(QColor("#F5F5F5"))

        self.clear_format = QTextCharFormat()
        self.clear_format.setBackground(QColor("transparent"))

    def _setup_config_and_nlp(self):
        APP_NAME = "FocalReader"
        APP_AUTHOR = "Maksymilian Wicinski"
        dirs = AppDirs(APP_NAME, APP_AUTHOR)
        self.config_path = os.path.join(dirs.user_config_dir, "config.ini")
        
        self.tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')
        custom_abbreviations = {'etc', 'mr', 'mrs', 'ms', 'dr', 'prof', 'rev', 'capt', 'sgt', 'col', 'gen', 'vs', 'no', 'e.g', 'i.e', 'et al'}
        self.tokenizer._params.abbrev_types.update(custom_abbreviations)

    def _apply_highlight(self, start, end, text_format):
        cursor = self.text_area.textCursor()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, end - start)
        cursor.mergeCharFormat(text_format)
        return cursor

    def _clear_highlight(self, highlighter):
        if highlighter:
            highlighter.mergeCharFormat(self.clear_format)

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
        if self.playback_state == "PLAYING" or not self.sentences: return
        # This check is now a bit redundant since the handler also checks, but it's good for catching issues early.
        if not self.azure_key or not self.azure_region:
            self.open_settings(); return
        
        self.playback_state = "PLAYING"
        # The line below was duplicated. This is the corrected version.
        self._play_sentence(self.current_sentence_index)

    def _play_sentence(self, index):
        if self.playback_state != "PLAYING" or index >= len(self.sentences):
            self.stop_tts(); return

        self.current_sentence_index = index
        text_to_speak = self.sentences[index]
        
        self._clear_highlight(self.hover_highlighter)
        self._clear_highlight(self.playback_highlighter)
        start, end = self.sentence_spans[index]
        self.playback_highlighter = self._apply_highlight(start, end, self.playback_format)

        # Delegate the actual work to the handler
        self.tts_handler.play(text_to_speak)

    def stop_tts(self):
        if self.playback_state == "STOPPED": return
        self.playback_state = "STOPPED"
        self.tts_handler.stop()
    
    def _on_playback_started(self):
        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.set_nav_buttons_enabled(True)

    def _on_playback_stopped(self):
        self._clear_highlight(self.playback_highlighter)
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.set_nav_buttons_enabled(bool(self.sentences))

    def _on_sentence_finished(self):
        """ This is the new continuous playback loop. """
        if self.playback_state != "PLAYING": return
        
        next_index = self.current_sentence_index + 1
        if next_index < len(self.sentences):
            self._play_sentence(next_index)
        else:
            print("Finished reading all sentences.")
            self.stop_tts()

    def on_tts_error(self, error_message):
        QMessageBox.critical(self, "An Azure TTS Error Occurred", error_message)
        self.stop_tts()
    
    def set_nav_buttons_enabled(self, enabled):
        self.prev_sentence_button.setEnabled(enabled)
        self.next_sentence_button.setEnabled(enabled)
        self.prev_paragraph_button.setEnabled(enabled)
        self.next_paragraph_button.setEnabled(enabled)

    def load_previous_page(self):
        if self.current_file_path is None or self.current_start_page <= 0:
            return
        
        new_start_page = self.current_start_page - 1
        print(f"Attempting to reload from page {new_start_page}...")
        # We can just call the handler again with a start page override
        content, _, _ = self.pdf_handler.process_pdf(self.current_file_path, start_page_override=new_start_page)
        self._process_pdf_text(content)
        self.current_start_page = new_start_page
    
    def jump_to_anchor(self, anchor_name):
        """Scrolls the text area to the specified HTML anchor."""
        print(f"Jumping to anchor: {anchor_name}")
        self.text_area.scrollToAnchor(anchor_name)
    
    def open_file(self):
        if self.playback_state != "STOPPED": self.stop_tts()
        file_path, _ = QFileDialog.getOpenFileName(self, "Open File", "", "All Readable Files (*.txt *.pdf *.epub);;All Files (*)")
        if not file_path: return
        self.current_file_path = file_path
        self.emergency_button.setEnabled(False) # Disable by default
        try:
            if file_path.lower().endswith('.pdf'):
                content, self.toc_destinations, self.current_start_page = self.pdf_handler.process_pdf(file_path)
                self.emergency_button.setEnabled(True)
                self._process_pdf_text(content)
            elif file_path.lower().endswith('.epub'):
                final_html, final_plain_text, ui_toc_data = self.epub_handler.process_epub(file_path)
                print("\n--- Interactive TOC Data Received by MainWindow ---")
                for title, anchor in ui_toc_data:
                    print(f"  Title: {title}, Anchor: {anchor}")
                self.toc_widget.populate_toc(ui_toc_data)
                self.text_area.setHtml(final_html)
                self._process_epub_text(final_plain_text, update_display=False)
                self.emergency_button.setEnabled(False)
            else:
                with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
                self.current_start_page = 0
                self._process_pdf_text(content)
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Error Reading File", f"Could not read the file.\n\nError: {e}")

    def _process_pdf_text(self, raw_text):
        """
        Processes plain text extracted from PDF or TXT files.
        This method is responsible for text cleaning, paragraph unwrapping,
        and building the sentence/paragraph maps for navigation.
        """
        print("Processing PDF/TXT text...")
        
        self.sentences = []
        self.sentence_spans = []
        self.paragraph_sentence_map = []
        
        if not raw_text:
            self.text_area.setText("")
            self.stop_tts()
            return

        combined_pattern_str = r'([^\.\?!])\s*\n(?=(?:' + '|'.join(self.chapter_keywords) + r'))'
        raw_text = re.sub(combined_pattern_str, r'\1.\n', raw_text, flags=re.IGNORECASE)

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

        full_text_for_analysis = self.text_area.toPlainText()
        self.sentence_spans = list(self.tokenizer.span_tokenize(full_text_for_analysis))
        self.sentences = [full_text_for_analysis[start:end] for start, end in self.sentence_spans]
        self.paragraph_sentence_map = []
        if not self.sentences:
            self.stop_tts()
            return

        current_paragraph_indices = []
        for i, (start, end) in enumerate(self.sentence_spans):
            current_paragraph_indices.append(i)
            is_last_sentence = (i == len(self.sentence_spans) - 1)
            check_start = end
            check_end = len(full_text_for_analysis)
            if not is_last_sentence:
                check_end = self.sentence_spans[i + 1][0]
            
            intervening_text = full_text_for_analysis[check_start:check_end]
            if "\n\n" in intervening_text or is_last_sentence:
                self.paragraph_sentence_map.append(current_paragraph_indices)
                current_paragraph_indices = []

        print(f"Processed {len(self.sentences)} sentences in {len(self.paragraph_sentence_map)} paragraphs.")
        self.current_sentence_index = 0
        nav_enabled = bool(self.sentences)
        self.prev_sentence_button.setEnabled(nav_enabled)
        self.next_sentence_button.setEnabled(nav_enabled)
        self.prev_paragraph_button.setEnabled(nav_enabled)
        self.next_paragraph_button.setEnabled(nav_enabled)

    def _process_epub_text(self, raw_text, update_display=True):
        """
        Processes the plain text extracted from EPUB files.
        This method builds the sentence/paragraph maps from the widget's content
        to ensure highlighting and navigation work correctly with HTML.
        """
        print("Processing EPUB text...")
        
        self.sentences = []
        self.sentence_spans = []
        self.paragraph_sentence_map = []
        
        if not raw_text:
            self.text_area.setText("")
            self.stop_tts()
            return

        final_text = raw_text.replace('\u2028', '\n')
        
        if update_display:    
            self.text_area.setText(final_text)

        full_text_for_analysis = self.text_area.toPlainText()
        self.sentence_spans = list(self.tokenizer.span_tokenize(full_text_for_analysis))
        self.sentences = [full_text_for_analysis[start:end] for start, end in self.sentence_spans]

        if not self.sentences:
            self.stop_tts()
            return

        doc = self.text_area.document()
        block = doc.begin()
        sentence_cursor = 0
        
        while block.isValid():
            block_text = block.text()
            if not block_text.strip():
                block = block.next()
                continue

            first_sentence_in_block = sentence_cursor
            block_end_pos = block.position() + block.length()
            
            while (sentence_cursor < len(self.sentence_spans) and 
                   self.sentence_spans[sentence_cursor][1] <= block_end_pos):
                sentence_cursor += 1
            
            last_sentence_in_block = sentence_cursor
            para_indices = list(range(first_sentence_in_block, last_sentence_in_block))
            if para_indices:
                self.paragraph_sentence_map.append(para_indices)
            block = block.next()

        print(f"Processed {len(self.sentences)} sentences in {len(self.paragraph_sentence_map)} paragraphs.")
        self.current_sentence_index = 0
        nav_enabled = bool(self.sentences)
        self.prev_sentence_button.setEnabled(nav_enabled)
        self.next_sentence_button.setEnabled(nav_enabled)
        self.prev_paragraph_button.setEnabled(nav_enabled)
        self.next_paragraph_button.setEnabled(nav_enabled)

    def open_emergency_menu(self):
        dialog = EmergencyDialog(self)

        dialog.fix_start_requested.connect(self.load_previous_page)
        dialog.new_footer_requested.connect(self.add_and_reprocess_footer)

        dialog.exec()

    def add_and_reprocess_footer(self, footer_text):
        # Add the new pattern and re-process the file
        new_pattern = re.compile(re.escape(footer_text), re.IGNORECASE)
        self.footer_patterns.append(new_pattern)
        self.reprocess_current_file()

    def reprocess_current_file(self):
        if not self.current_file_path:
            return
        
        print("Re-processing current file with new settings...")
        # The handler will now automatically use the updated footer_patterns list
        content, self.toc_destinations, self.current_start_page = self.pdf_handler.process_pdf(self.current_file_path)
        self._process_pdf_text(content)
    
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
        
        # THE FIX: Pass the loaded credentials to the TTSHandler.
        if self.azure_key and self.azure_region:
            self.tts_handler.set_credentials(self.azure_key, self.azure_region)