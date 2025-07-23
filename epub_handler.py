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
        Returns styled HTML, plain text, TOC data, and grouped insert images.
        """
        self.book = epub.read_epub(file_path)
        toc_data = self._find_essential_files_in_toc()
        essential_hrefs = {href for title, href in toc_data}

        # _get_epub_chapter_groups now correctly returns the list of non-text files
        chapter_groups, non_text_docs_map, all_docs_in_order = self._get_epub_chapter_groups(essential_hrefs)
        
        image_map = self._extract_images_from_non_text_files(non_text_docs_map)
        grouped_images = self._group_images(chapter_groups, image_map, all_docs_in_order)

        # Pass the image map to the processor so it knows where placeholders should go
        final_html, final_plain_text, ui_toc = self._process_epub_chapters(chapter_groups, toc_data, image_map)
        
        return final_html, final_plain_text, ui_toc, grouped_images

    def _group_images(self, chapter_groups, image_map, all_docs_in_order):
        """
        Categorizes images into cover, chapter-specific, and ending groups.
        """
        print("\n--- Helper: Grouping images ---")
        grouped = {
            "cover": [],
            "chapters": [[] for _ in chapter_groups],
            "ending": []
        }
        
        if not chapter_groups: # Handle books with no chapters
            for href, img_data in image_map.items():
                grouped["cover"].append(img_data)
            return grouped

        # Find the start and end points of the main chapter content
        first_chapter_start_index = all_docs_in_order.index(chapter_groups[0][0])
        last_chapter_end_index = all_docs_in_order.index(chapter_groups[-1][-1])
        href_to_chapter_index = {href: i for i, group in enumerate(chapter_groups) for href in group}

        # Categorize each non-text document
        for i, doc_href in enumerate(all_docs_in_order):
            if doc_href in image_map:
                image_content_list = image_map[doc_href]
                if i < first_chapter_start_index:
                    grouped["cover"].extend(image_content_list)
                elif i > last_chapter_end_index:
                    grouped["ending"].extend(image_content_list)
                else:
                    current_chapter_index = -1
                    for doc_idx in range(i, -1, -1):
                        potential_chapter_href = all_docs_in_order[doc_idx]
                        if potential_chapter_href in href_to_chapter_index:
                            current_chapter_index = href_to_chapter_index[potential_chapter_href]
                            break
                    if current_chapter_index != -1:
                        grouped["chapters"][current_chapter_index].extend(image_content_list)

        print(f"[RESULT] Image Groups: {len(grouped['cover'])} cover, "
              f"{sum(len(c) for c in grouped['chapters'])} chapter, "
              f"{len(grouped['ending'])} ending images.")
        return grouped

    
    def _find_essential_files_in_toc(self):
        print("\n--- Helper: Finding Essential Chapters from Table of Contents ---")
        toc_data = []
        if not self.book.toc:
            print("[WARNING] Book has no identifiable Table of Contents (book.toc).")
            return toc_data

        for link in self.book.toc:
            for keyword in self.chapter_keywords:
                if keyword in link.title.lower():
                    title = link.title
                    href = link.href.split('#')[0]
                    print(f"  -> Found essential chapter in TOC: '{title}' -> {href}")
                    toc_data.append((title, href))
                    break
        
        print(f"\n[RESULT] Essential files from TOC: {len(toc_data)} entries found. \nFiles: {toc_data}")
        return toc_data

    def _extract_images_from_non_text_files(self, non_text_docs_map):
        """
        Parses a list of non-text documents, finds image tags,
        and extracts the actual image data from the book's manifest.
        """
        print("\n--- Helper: Extracting Images from Non-Text Documents ---")
        image_map = {}
        href_to_item_map = {item.get_name(): item for item in self.book.get_items()}
        image_counter = 0

        for doc_href, html_content in non_text_docs_map.items():
            soup = BeautifulSoup(html_content, 'html.parser')
            doc_images = []
            for img_tag in soup.find_all('img'):
                img_src = img_tag.get('src')
                if not img_src: continue
                clean_href = img_src.split('/')[-1]
                for item_href, item in href_to_item_map.items():
                    if item_href.endswith(clean_href) and item.get_type() == ebooklib.ITEM_IMAGE:
                        image_id = f"image-{image_counter}"
                        # --- BUG FIX #1: Correctly increment the counter ---
                        image_counter += 1
                        doc_images.append((image_id, item.get_content()))
                        print(f"  -> Found embedded image: {item_href} (ID: {image_id})")
                        break
            if doc_images:
                image_map[doc_href] = doc_images
        
        print(f"[RESULT] Found {image_counter} images in {len(image_map)} non-text documents.")
        return image_map

    def _get_epub_chapter_groups(self, essential_files_from_toc):
        print("\n--- RUNNING 'SOURCE OF TRUTH' FILE IDENTIFICATION ---")
        skip_keywords = [
            'copyright', 'isbn', 'translation by', 'cover art', 'yen press',
            'kadawa', 'tuttle-mori', 'library of congress', 'lccn', 'e-book',
            'ebook', 'first published', 'english translation', 'visit us at',
            'novel', 'download'
        ]
        kept_files, discarded_files = [], []
        non_text_docs_map = {} # Maps href to content for non-text docs
        JUNK_CHECK_LIMIT = 5

        id_to_item_map = {item.id: item for item in self.book.get_items()}
        spine_ids = [item[0] for item in self.book.spine]
        all_document_hrefs = []
        documents_checked_count = 0

        for item_id in spine_ids:
            item = id_to_item_map.get(item_id)
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT and item.get_name() not in all_document_hrefs:
                all_document_hrefs.append(item.get_name())
        
        for file_href in all_document_hrefs:
            item = self.book.get_item_with_href(file_href)
            html_content = item.get_content()
            text_content = BeautifulSoup(html_content, 'html.parser').get_text().strip()

            if not text_content:
                non_text_docs_map[file_href] = html_content
                kept_files.append(file_href) # Keep non-text files for now
            elif documents_checked_count < JUNK_CHECK_LIMIT:
                documents_checked_count += 1
                if any(keyword in text_content.lower() for keyword in skip_keywords):
                    discarded_files.append(file_href)
                else:
                    kept_files.append(file_href)
            else:
                kept_files.append(file_href)

        # (Rollback logic is unchanged)
        missing_essentials = essential_files_from_toc - set(kept_files)
        while missing_essentials and discarded_files:
            file_to_restore = discarded_files.pop()
            kept_files.insert(0, file_to_restore)
            missing_essentials = essential_files_from_toc - set(kept_files)
        
        kept_files.sort(key=all_document_hrefs.index)
        
        # --- THE FIX IS HERE ---
        # Now that we have the final, clean list of files, we will discard
        # everything before the first essential chapter.
        
        first_chapter_start_index = -1
        for i, href in enumerate(kept_files):
            if href in essential_files_from_toc:
                first_chapter_start_index = i
                break
        
        if first_chapter_start_index != -1:
            print(f"  -> First real chapter starts at index {first_chapter_start_index}. Trimming pre-chapter content.")
            # This is our final list of TRUE content files.
            final_content_files = kept_files[first_chapter_start_index:]
        else:
            # If no essential chapters were found, keep everything as a fallback.
            print("  -> WARNING: Could not find a start chapter. Keeping all content.")
            final_content_files = kept_files

        # --- Grouping logic now uses the truly final list ---
        final_chapter_groups = []
        if final_content_files:
            current_group = [final_content_files[0]]
            for i in range(1, len(final_content_files)):
                file_href = final_content_files[i]
                if file_href in essential_files_from_toc:
                    final_chapter_groups.append(current_group)
                    current_group = [file_href]
                else:
                    current_group.append(file_href)
            final_chapter_groups.append(current_group)

        return final_chapter_groups, non_text_docs_map, all_document_hrefs
    
    def _process_epub_chapters(self, chapter_groups, toc_data, image_map):
        print("\n--- Phase 2: Running Dual Output Processor with Placeholders ---")
        html_body_parts, plain_text_parts, ui_toc = [], [], []
        href_to_title_map = {href: title for title, href in toc_data}
        default_css = """
        <style>
            body { font-family: serif; font-size: 16px; line-height: 1.6; margin: 20px; }
            h1, h2, h3 { font-family: sans-serif; margin-top: 30px; margin-bottom: 10px; line-height: 1.2; }
        </style>
        """
        
        for i, group in enumerate(chapter_groups):
            first_file_href = group[0]
            anchor_name = f"chapter-anchor-{i}"
            is_essential_chapter = first_file_href in href_to_title_map
            
            if is_essential_chapter:
                ui_toc.append((href_to_title_map[first_file_href], anchor_name))

            for file_href in group:
                if file_href in image_map:
                    for image_id, image_data in image_map[file_href]:
                        placeholder_html = f'<p style="text-align:center;"><a href="focal-reader:image:{image_id}">[SEE IMAGE HERE.]</a></p>'
                        placeholder_text = "[SEE IMAGE HERE.]"
                        html_body_parts.append(placeholder_html)
                        plain_text_parts.append(placeholder_text)
                    continue
                
                item = self.book.get_item_with_href(file_href)
                if not item: continue
                
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                for tag in soup.find_all('link'): tag.decompose()
                for tag in soup.find_all(style=True): del tag['style']
                
                if soup.body:
                    if file_href == first_file_href and is_essential_chapter:
                        anchor_tag = soup.new_tag("a", attrs={"name": anchor_name})
                        soup.body.insert(0, anchor_tag)
                    html_body_parts.append(str(soup.body))

                for tag in soup.find_all(['h1', 'h2', 'h3', 'p']):
                    text = tag.get_text(strip=True)
                    if text: plain_text_parts.append(text)
        
        final_html = default_css + "".join(html_body_parts)
        final_plain_text = "\n\n".join(plain_text_parts)
        
        print(f"-> Generated {len(ui_toc)} TOC entries with anchors.")
        return final_html, final_plain_text, ui_toc