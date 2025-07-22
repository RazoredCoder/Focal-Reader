import os
import sys
import configparser
import nltk
import azure.cognitiveservices.speech as speechsdk
from appdirs import AppDirs
import fitz  # Import for PyMuPDF
import re # Import regular expressions for finding numbers

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

from PySide6.QtCore import QObject, QThread, Signal, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QTextCursor, QColor, QTextCharFormat
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTextEdit, 
                               QHBoxLayout, QPushButton, QFileDialog, QMessageBox)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from settings_dialog import SettingsDialog
from emergency_dialog import EmergencyDialog

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

        self.footer_patterns = [
            # Pattern 1: For footers like "Page 1 Goldenagato | mp4directs.com"
            re.compile(r'^Page\s+\d+', re.IGNORECASE),
            # Pattern 2: For footers like "11 | P a g e"
            re.compile(r'^\d+\s*\|\s*P\s*a\s*g\s*e', re.IGNORECASE),
        ]
        self.chapter_keywords = ['prologue', 'epilogue', 'chapter', 'appendix', 'afterword', 'interlude', 'side story']

        self.toc_pages = []
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
        self.emergency_button = QPushButton("Emergency Menu")

        controls_layout.addWidget(self.load_button)
        controls_layout.addWidget(self.emergency_button)
        # controls_layout.addWidget(self.fix_start_button)
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
        self.emergency_button.clicked.connect(self.open_emergency_menu)
        
        self.text_area.clicked_at_pos.connect(self.on_text_area_clicked)
        self.text_area.hovered_at_pos.connect(self.on_text_area_hovered)

        self.stop_button.setEnabled(False)
        self.prev_sentence_button.setEnabled(False)
        self.next_sentence_button.setEnabled(False)
        self.prev_paragraph_button.setEnabled(False)
        self.next_paragraph_button.setEnabled(False)
        self.fix_start_button.setEnabled(False)
        self.emergency_button.setEnabled(False)

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
        text = self._extract_text_from_pdf(doc, new_start_page, self.toc_destinations)
        self._process_text(text)
        self.current_start_page = new_start_page
    
    def open_file(self):
        if self.playback_state != "STOPPED": self.stop_tts()
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Open File", 
            "", 
            "All Readable Files (*.txt *.pdf *.epub);;Text Files (*.txt);;PDF Files (*.pdf);;EPUB Files (*.epub)"
        )
        if not file_path:
            return
        
        self.current_file_path = file_path
        
        try:
            # Logic for PDF files
            if file_path.lower().endswith('.pdf'):
                with fitz.open(file_path) as doc:
                    self.toc_destinations, self.current_start_page = self._parse_toc_links(doc)
                    content = self._extract_text_from_pdf(doc, self.current_start_page, self.toc_destinations)
                self.fix_start_button.setEnabled(True)
                self.emergency_button.setEnabled(True)
                # Call the dedicated PDF/TXT processor
                self._process_pdf_text(content)
            
            # Logic for EPUB files
            elif file_path.lower().endswith('.epub'):
                book = epub.read_epub(file_path)
                chapter_groups, non_text_files = self._get_epub_chapter_groups(book)
                final_html, final_plain_text = self._process_epub_chapters(book, chapter_groups)

                # Display the styled HTML
                self.text_area.setHtml(final_html)
                # Call the dedicated EPUB processor, telling it not to update the display
                self._process_epub_text(final_plain_text, update_display=False)
                
                self.fix_start_button.setEnabled(False)
                self.emergency_button.setEnabled(False)

            # Logic for plain text files
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.current_start_page = 0
                # Call the dedicated PDF/TXT processor
                self._process_pdf_text(content)

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error Reading File", f"Could not read the file.\n\nError: {e}")

    def _find_essential_files_in_toc(self, book):
        """
        Parses the book's Table of Contents to find the starting file (href)
        for each entry that looks like a real chapter.
        Returns a set of these essential file hrefs.
        """
        print("\n--- Helper: Finding Essential Chapters from Table of Contents ---")
        essential_files = set()
        if not book.toc:
            print("[WARNING] Book has no identifiable Table of Contents (book.toc).")
            return essential_files

        for link in book.toc:
            # This loop is already quite clear, but we can add a small print.
            # print(f"  -> Examining TOC entry: '{link.title}'")
            for keyword in self.chapter_keywords:
                if keyword in link.title.lower():
                    href = link.href.split('#')[0]
                    print(f"  -> Found essential chapter in TOC: '{link.title}' -> {href}")
                    essential_files.add(href)
                    break
        
        print(f"\n[RESULT] Essential files from TOC: {list(essential_files)}")
        return essential_files

    def _get_epub_chapter_groups(self, book):
        """
        Orchestrates the entire "Source of Truth" algorithm to produce a clean,
        grouped list of chapter files and a list of non-text files.
        """
        print("\n\n--- RUNNING 'SOURCE OF TRUTH' FILE IDENTIFICATION (VERBOSE) ---")

        # --- Initial Setup ---
        skip_keywords = [
            'copyright', 'isbn', 'translation by', 'cover art', 'yen press',
            'kadokawa', 'tuttle-mori', 'library of congress', 'lccn', 'e-book',
            'ebook', 'first published', 'english translation', 'visit us at'
        ]
        kept_files, discarded_files, non_text_files = [], [], []
        JUNK_CHECK_LIMIT = 5
        print(f"[CONFIG] Will check the first {JUNK_CHECK_LIMIT} real text documents for junk keywords.")

        # --- Phase 2 is now in a helper method ---
        essential_files_from_toc = self._find_essential_files_in_toc(book)

        # --- Phase 1: Splitting Spine into Kept and Discarded Files ---
        print("\n--- PHASE 1: Splitting Spine into Kept and Discarded Files ---")
        id_to_item_map = {item.id: item for item in book.get_items()}
        spine_ids = [item[0] for item in book.spine]
        documents_checked_count = 0
        all_document_hrefs = []

        for item_id in spine_ids:
            item = id_to_item_map.get(item_id)
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT and item.get_name() not in all_document_hrefs:
                all_document_hrefs.append(item.get_name())
        
        for file_href in all_document_hrefs:
            print(f"\n-> Processing: '{file_href}'")
            item = book.get_item_with_href(file_href)
            text_content = BeautifulSoup(item.get_content(), 'html.parser').get_text().strip()

            if not text_content:
                print("  -> Result: Document has NO TEXT. Adding to non-text list.")
                non_text_files.append(file_href)
                continue

            if documents_checked_count < JUNK_CHECK_LIMIT:
                print(f"  -> Document has text. Checking for junk (Document to check: #{documents_checked_count + 1}).")
                documents_checked_count += 1
                
                is_junk = any(keyword in text_content.lower() for keyword in skip_keywords)

                if is_junk:
                    print(f"  -> Result: Found junk keyword. DISCARDING.")
                    discarded_files.append(file_href)
                else:
                    print(f"  -> Result: No junk keywords found. KEEPING.")
                    kept_files.append(file_href)
            else:
                print("  -> Result: Past junk check limit. KEEPING.")
                kept_files.append(file_href)
        
        print("\n[Initial Lists] Kept: ", kept_files)
        print("[Initial Lists] Discarded: ", discarded_files)
        print("[Initial Lists] Non-Text Files: ", non_text_files)

        # --- Phase 3: Verification and Iterative Rollback ---
        print("\n--- PHASE 3: Verifying Kept Files and Rolling Back if Needed ---")
        missing_essentials = essential_files_from_toc - set(kept_files)
        if not missing_essentials:
            print("  -> No essential files are missing. No rollback needed.")

        while missing_essentials and discarded_files:
            print(f"  -> WARNING: Missing essential file(s) like '{list(missing_essentials)[0]}'. Rolling back.")
            file_to_restore = discarded_files.pop()
            kept_files.insert(0, file_to_restore)
            print(f"  -> Restored '{file_to_restore}' to the kept list.")
            missing_essentials = essential_files_from_toc - set(kept_files)
        
        kept_files.sort(key=all_document_hrefs.index)
        print(f"\n[Final List] Final kept files after rollback: {kept_files}")

        # --- Final Step: Chapter Grouping ---
        print("\n--- FINAL STEP: Grouping Chapter Files ---")
        final_chapter_groups = []
        if kept_files:
            current_group = [kept_files[0]]
            for i in range(1, len(kept_files)):
                file_href = kept_files[i]
                if file_href in essential_files_from_toc:
                    final_chapter_groups.append(current_group)
                    current_group = [file_href]
                else:
                    current_group.append(file_href)
            final_chapter_groups.append(current_group)

        print(f"[Chapter Groups] Found {len(final_chapter_groups)} chapter groups.")
        for i, group in enumerate(final_chapter_groups):
            print(f"  -> Group {i+1}: {group}")

        return final_chapter_groups, non_text_files
    
    def _process_epub_chapters(self, book, chapter_groups):
        """
        Process the grouped chapter files to produce two distinct outputs:
        1. A single, sanitized HTML string with custom CSS for display.
        2. A single, clean plain-text string with proper paragraph breaks for TTS/naivation,
        """
        print("\n--- Phase 2: Running Dual Output Processor ---")
        html_body_parts = []
        plain_text_parts = []
        default_css = """
        <style>
            body {
                font-family: serif;
                font-size: 16px;
                line-height: 1.6;
                margin: 20px;
            }
            h1, h2, h3 {
                font-family: sans-serif;
                margin-top: 30px;
                margin-bottom: 10px;
                line-height: 1.2;
            }
        </style>
        """
        
        for i, group in enumerate(chapter_groups):
            print(f"  -> Processing Group {i+1}/{len(chapter_groups)}")
            for file_href in group:
                item = book.get_item_with_href(file_href)
                if not item:
                    continue

                soup = BeautifulSoup(item.get_content(), 'html.parser')

                for tag in soup.find_all('link'):
                    tag.decompose()
                for tag in soup.find_all(style=True):
                    del tag['style']

                if soup.body:
                    html_body_parts.append(str(soup.body))
                
                for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
                    text = tag.get_text(strip=True)
                    if text:
                        plain_text_parts.append(text)
        
        final_html = default_css + "".join(html_body_parts)
        final_plain_text = "\n\n".join(plain_text_parts)

        print("-> Finished processing. Returning final HTML and plain text.")
        return final_html, final_plain_text
    
    def _extract_raw_html_from_epub(self, book, chapter_groups):
        """
        (Dummy Method) Extracts the raw, combined HTML content from the chapter groups.
        For now, it simply gets the content of each file and joins them.
        """
        print("\n--- DUMMY: Extracting Raw HTML ---")
        all_html_parts = []
        for group in chapter_groups:
            for file_href in group:
                item = book.get_item_with_href(file_href)
                if item:
                    # get_content() returns bytes, so we decode it to a string.
                    # 'ignore' will prevent crashes if there are weird characters.
                    all_html_parts.append(item.get_content().decode('utf-8', 'ignore'))
        
        # We join the HTML of each file with a horizontal rule for a clear visual separation.
        return "<hr>".join(all_html_parts)

    def _process_epub_content(self, raw_html):
        """
        (Dummy Method) Processes the extracted ePub content. For now, it just
        displays the raw HTML and resets navigation/TTS data to prevent crashes.
        """
        print("\n--- DUMMY: Processing ePub Content ---")
        # Clear all data structures related to TTS and navigation.
        self.sentences = []
        self.sentence_spans = []
        self.paragraph_sentence_map = []
        self.current_sentence_index = 0
        
        # Disable navigation buttons since we have no sentence data yet.
        self.prev_sentence_button.setEnabled(False)
        self.next_sentence_button.setEnabled(False)
        self.prev_paragraph_button.setEnabled(False)
        self.next_paragraph_button.setEnabled(False)
        
        # Use setHtml to render the raw HTML in the text widget.
        self.text_area.setHtml(raw_html)
        print("-> Displayed raw HTML in the text area.")
    
    def _parse_toc_links(self, doc):
        raw_links = []
        has_empty_links = False
        for page_num in range(min(15, len(doc))):
            page = doc.load_page(page_num)
            link_list = page.get_links()

            print(f"--- Page {page_num + 1} ---")
            for link in link_list:
                link_text = page.get_text("text", clip=link['from']).strip()
                if not link_text:
                    has_empty_links = True
                raw_links.append({'link_obj': link, 'text': link_text, 'source_page': page_num})
                
                print(f"Found a link: {link}")
                print(f"Its link text is {link_text}")

        toc_page_candidates = []

        if has_empty_links:
            print("DEBUG: Empty links detected. Using full-page text analysis to find TOC.")

            toc_keyword_pattern = re.compile('|'.join(self.chapter_keywords), re.IGNORECASE)
            for page_num in range(min(15, len(doc))):
                if any(link['source_page'] == page_num for link in raw_links):
                    page_text = doc.load_page(page_num).get_text().lower()
                    matches = toc_keyword_pattern.findall(page_text)
                    occurrence_count = len(matches)

                    print(f"DEBUG: Page {page_num} has {occurrence_count} keyword occurrences.")

                    if occurrence_count > 4:
                        toc_page_candidates.append(page_num)
        
        else:
            print("DEBUG: Standard links detected. Using link text analysis to find TOC.")
            for link_data in raw_links:
                for keyword in self.chapter_keywords:
                    if keyword in link_data['text'].lower():
                        if link_data['source_page'] not in toc_page_candidates:
                            toc_page_candidates.append(link_data['source_page'])
                        break
        
        print(f"================== Table of content page candidates: {toc_page_candidates} =======================")

        first_page = self._detect_pdf_start_page(toc_page_candidates)
        if not first_page:
            return [], 0
        
        toc_destinations = []
        
        if has_empty_links and self.toc_pages:

            try:
                print("DEBUG: Attempting to parse TOC from text block...")
                toc_text_block = ""
                for page_num in self.toc_pages:
                    page = doc.load_page(page_num)
                    toc_text_block += self._clean_text_of_footers(page.get_text())
                
                all_titles = re.split(r'(?<=[a-z?!])(?=[A-Z])', toc_text_block)
                all_titles = [title.strip() for title in all_titles if "Table of Contents" not in title and title.strip()]
                
                toc_links_on_pages = [link['link_obj'] for link in raw_links if link['source_page'] in self.toc_pages]
                
                unique_links = []
                seen_pages_for_links = set()
                for link_obj in toc_links_on_pages:
                    dest_page = link_obj['page']
                    if dest_page not in seen_pages_for_links:
                        unique_links.append(link_obj)
                        seen_pages_for_links.add(dest_page)
                
                all_toc_pairs = zip(all_titles, unique_links)

                toc_destinations = []
                seen_pages = set()
                for title, link_obj in all_toc_pairs:
                    dest_page = link_obj['page']
                    if dest_page in seen_pages:
                        continue
                    
                    for keyword in self.chapter_keywords:
                        if keyword in title.lower():
                            toc_destinations.append({
                                'text': title,
                                'dest_page': dest_page
                            })
                            seen_pages.add(dest_page)
                            break

            except Exception as e:
                print(f"ERROR: Special TOC parsing failed: {e}")
        
        if not toc_destinations:
            for link_data in raw_links:
                if link_data['source_page'] in self.toc_pages:
                    for keyword in self.chapter_keywords:
                        if keyword.lower() in link_data['text'].lower():
                            toc_destinations.append({
                                'text': link_data['text'].replace('\n', ' ').strip(),
                                'dest_page': link_data['link_obj']['page']
                            })
                            break

        return toc_destinations, first_page
        
    
    def _detect_pdf_start_page(self, candidates):
        toc_page_candidates = candidates
        
        true_last_toc_page = -1
        true_toc_pages = []
        
        unique_candidates = sorted(list(set(toc_page_candidates)))
        if unique_candidates:
            first_toc_page = unique_candidates[0]
            true_toc_pages.append(first_toc_page)
            true_last_toc_page = first_toc_page

            for i in range (1, len(unique_candidates)):
                if unique_candidates[i] == unique_candidates[i-1] + 1:
                    true_toc_pages.append(unique_candidates[i])
                    true_last_toc_page = unique_candidates[i]
                
                else:
                    break
        self.toc_pages = true_toc_pages
        print(f"================== The true TOC pages are: {self.toc_pages} =======================")
        print(f"================== The real last TOC page is: {true_last_toc_page} =======================")
        return true_last_toc_page + 1

    def _should_skip_block(self, block_text, y_pos, page_height):
        if y_pos > (page_height * 0.9) and len(block_text) < 100:
            for keyword in self.chapter_keywords:
                if keyword in block_text.lower():
                    return False
            
            if re.search(r'\d', block_text):
                return True
            return False
        
    def _clean_text_of_footers(self, block_text):
        cleaned_text = block_text
        for pattern in self.footer_patterns:
            cleaned_text = pattern.sub('', cleaned_text)
        return cleaned_text.strip()

    def _extract_text_from_pdf(self, doc, start_page, toc_destinations):
        full_text_parts = []
        skip_next_page = False
        para_break_placeholder = " [PARA_BREAK] "
        toc_titles = {entry['text'].strip() for entry in toc_destinations}


        for page_num in range(start_page, len(doc)):
            if skip_next_page:
                skip_next_page = False
                continue
            
            page = doc.load_page(page_num)
            page_height = page.rect.height
            # Helper function to get a clean list of text strings from a page's blocks.
            def get_content_text_list(p):
                text_list = []
                raw_blocks = p.get_text("blocks")
                for block in raw_blocks:
                    if block[6] in [0, 1]: 
                        block_text = block[4].strip()
                        y_pos = block[1]
                        
                        if self._should_skip_block(block_text, y_pos, p.rect.height):
                            print(f"Skipped isolated footer on page {p.number + 1}: '{block_text.strip()}")
                            continue

                        cleaned_text = self._clean_text_of_footers(block_text)

                        if cleaned_text:
                            text_list.append(cleaned_text)
                        
                return text_list

            page_content_text = get_content_text_list(page)

            chapter_title_for_this_page = None
            for toc_entry in toc_destinations:
                if toc_entry['dest_page'] == page_num:
                    chapter_title_for_this_page = toc_entry['text']
                    break
            
            if chapter_title_for_this_page and not page_content_text:
                if (page_num + 1) < len(doc):
                    next_page = doc.load_page(page_num + 1)
                    page_content_text = get_content_text_list(next_page)
                    skip_next_page = True


            if chapter_title_for_this_page:
                top_block_text = ""
                if page_content_text:
                    top_block_text = page_content_text[0]

                cleaned_top_block = top_block_text.replace('\n', ' ').replace(' ', '').lower()
                cleaned_toc_title = chapter_title_for_this_page.replace('\n', ' ').replace(' ', '').lower()

                # --- START OF DEBUG BLOCK ---
                print(f"\n----- TITLE CHECK ON PAGE {page_num} -----")
                print(f"Cleaned TOC Title: '{cleaned_toc_title}'")
                print(f"Cleaned Top Block: '{cleaned_top_block}'")
                
                is_missing_currently = cleaned_toc_title not in cleaned_top_block
                print(f"  -> Is title missing (our current, flawed logic)? {is_missing_currently}")

                is_missing_correctly = cleaned_top_block not in cleaned_toc_title
                print(f"  -> Is title missing (the correct logic)? {is_missing_correctly}")
                print("---------------------------------\n")
                # --- END OF DEBUG BLOCK ---

                if cleaned_top_block not in cleaned_toc_title:
                    page_content_text.insert(0, chapter_title_for_this_page.strip())
            
            full_text_parts.extend(page_content_text)

        final_text = ""
        for i, part in enumerate(full_text_parts):
            final_text += part
            if part.strip() in toc_titles:
                final_text += "\n\n"
            else:
                if i < len(full_text_parts) - 1:
                    final_text += "\n"

        return final_text            

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
        new_pattern = re.compile(re.escape(footer_text), re.IGNORECASE)

        self.footer_patterns.append(new_pattern)
        self.reprocess_current_file()

    def reprocess_current_file(self):
        if not self.current_file_path:
            return
        
        print("Re-processing current file with the new settings...")
        try:
            with fitz.open(self.current_file_path) as doc:
                content = self._extract_text_from_pdf(doc, self.current_start_page, self.toc_destinations)
                self._process_text(content)
        except Exception as e:
            QMessageBox.critical(self, "Error Re-processing File", f"Could not re-read the file. \n\nError: {e}")
    
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
