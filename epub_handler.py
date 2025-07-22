import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

class EpubHandler:
    def __init__(self, chapter_keywords):
        self.book = None
        self.chapter_keywords = chapter_keywords

    def process_epub(self, file_path):
        """
        Main public method to process an EPUB file.
        Returns the styled HTML and the clean plain text.
        """
        print("\n--- Starting EPUB loading process ---")
        self.book = epub.read_epub(file_path)
        chapter_groups, _ = self._get_epub_chapter_groups()
        final_html, final_plain_text = self._process_epub_chapters(chapter_groups)
        return final_html, final_plain_text

    def _find_essential_files_in_toc(self):
        # (This method was moved from MainWindow)
        print("\n--- Helper: Finding Essential Chapters from Table of Contents ---")
        essential_files = set()
        if not self.book.toc:
            print("[WARNING] Book has no identifiable Table of Contents (book.toc).")
            return essential_files

        for link in self.book.toc:
            for keyword in self.chapter_keywords:
                if keyword in link.title.lower():
                    href = link.href.split('#')[0]
                    print(f"  -> Found essential chapter in TOC: '{link.title}' -> {href}")
                    essential_files.add(href)
                    break
        
        print(f"\n[RESULT] Essential files from TOC: {list(essential_files)}")
        return essential_files

    def _get_epub_chapter_groups(self):
        # (This method was moved from MainWindow)
        print("\n\n--- RUNNING 'SOURCE OF TRUTH' FILE IDENTIFICATION (VERBOSE) ---")
        skip_keywords = [
            'copyright', 'isbn', 'translation by', 'cover art', 'yen press',
            'kadawa', 'tuttle-mori', 'library of congress', 'lccn', 'e-book',
            'ebook', 'first published', 'english translation', 'visit us at'
        ]
        kept_files, discarded_files, non_text_files = [], [], []
        JUNK_CHECK_LIMIT = 5
        print(f"[CONFIG] Will check the first {JUNK_CHECK_LIMIT} real text documents for junk keywords.")

        essential_files_from_toc = self._find_essential_files_in_toc()

        print("\n--- PHASE 1: Splitting Spine into Kept and Discarded Files ---")
        id_to_item_map = {item.id: item for item in self.book.get_items()}
        spine_ids = [item[0] for item in self.book.spine]
        documents_checked_count = 0
        all_document_hrefs = []

        for item_id in spine_ids:
            item = id_to_item_map.get(item_id)
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT and item.get_name() not in all_document_hrefs:
                all_document_hrefs.append(item.get_name())
        
        for file_href in all_document_hrefs:
            item = self.book.get_item_with_href(file_href)
            text_content = BeautifulSoup(item.get_content(), 'html.parser').get_text().strip()

            if not text_content:
                non_text_files.append(file_href)
                continue

            if documents_checked_count < JUNK_CHECK_LIMIT:
                documents_checked_count += 1
                if any(keyword in text_content.lower() for keyword in skip_keywords):
                    discarded_files.append(file_href)
                else:
                    kept_files.append(file_href)
            else:
                kept_files.append(file_href)

        print("\n--- PHASE 3: Verifying Kept Files and Rolling Back if Needed ---")
        missing_essentials = essential_files_from_toc - set(kept_files)
        while missing_essentials and discarded_files:
            file_to_restore = discarded_files.pop()
            kept_files.insert(0, file_to_restore)
            missing_essentials = essential_files_from_toc - set(kept_files)
        
        kept_files.sort(key=all_document_hrefs.index)

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

        return final_chapter_groups, non_text_files
    
    def _process_epub_chapters(self, chapter_groups):
        # (This method was moved from MainWindow)
        print("\n--- Phase 2: Running Dual Output Processor ---")
        html_body_parts = []
        plain_text_parts = []
        default_css = """
        <style>
            body { font-family: serif; font-size: 16px; line-height: 1.6; margin: 20px; }
            h1, h2, h3 { font-family: sans-serif; margin-top: 30px; margin-bottom: 10px; line-height: 1.2; }
        </style>
        """
        
        for group in chapter_groups:
            for file_href in group:
                item = self.book.get_item_with_href(file_href)
                if not item: continue
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                for tag in soup.find_all('link'): tag.decompose()
                for tag in soup.find_all(style=True): del tag['style']
                if soup.body: html_body_parts.append(str(soup.body))
                for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
                    text = tag.get_text(strip=True)
                    if text: plain_text_parts.append(text)
        
        final_html = default_css + "".join(html_body_parts)
        final_plain_text = "\n\n".join(plain_text_parts)
        return final_html, final_plain_text