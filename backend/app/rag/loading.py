"""
STEP 1: LOAD. Turn a file into plain text, keeping track of WHERE each piece came from.

Why this step matters:
  An LLM can only read text, so every format (PDF, Word, Markdown, web page)
  has to be turned into plain text first. The important design choice here is
  to keep ONE record PER PAGE (PDF) or PER SECTION (everything else), instead
  of gluing the whole document into one long string. Gluing is the easy thing
  to do, but it throws the page numbers away, and then we could never show a
  citation like "notes.pdf, page 12".

What comes out:
  A list of `Page` records. Each has a 1-based number, a human-readable label
  used in citations ("page 12" or "section 3: Networking"), and its text.
  The ingestion job saves this list as JSON in data/collections/<id>/raw/, so a
  re-index (for example after changing chunk size) can skip this step entirely.
"""

import re
from dataclasses import asdict, dataclass
from pathlib import Path

# File types the loader knows how to read.
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}


@dataclass
class Page:
    """One page (PDF) or section (other formats) of extracted text, plus where it came from."""

    number: int  # PDF page number, or section number for formats without pages
    label: str   # what a citation shows: "page 3" or "section 2: Installation"
    text: str

    def to_dict(self) -> dict:
        """Plain-dict form, used when saving the pages as JSON."""
        return asdict(self)


class LoadError(Exception):
    """The file is corrupt, of an unsupported type, or contains no extractable text."""


def load_file(path: Path) -> list[Page]:
    """Entry point: pick the loader that matches the file extension."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        pages = load_pdf(path)
    elif ext == ".docx":
        pages = load_docx(path)
    elif ext in {".md", ".markdown"}:
        pages = load_markdown(read_text_file(path))
    elif ext == ".txt":
        pages = load_plain_text(read_text_file(path))
    else:
        raise LoadError(f"Unsupported file type: {ext}")
    # A file that parses but yields no text is useless to search, so say so clearly.
    if not pages:
        raise LoadError("No text could be extracted (is it a scanned/image-only document?)")
    return pages


def load_pdf(path: Path) -> list[Page]:
    """
    PDF: one Page per document page.

    PyPDFLoader (from LangChain) returns one Document per PDF page, with the
    0-based page index in its metadata. We keep that separation and convert to
    1-based numbers because that is what people see in a PDF viewer.
    Note: scanned PDFs are images, so they have no text layer. They would need
    OCR, which this app does not do.
    """
    from langchain_community.document_loaders import PyPDFLoader

    try:
        documents = list(PyPDFLoader(str(path)).lazy_load())
    except Exception as exc:  # pypdf raises many different error types for broken files
        raise LoadError(f"Could not read PDF: {exc}") from exc

    pages = []
    for doc in documents:
        text = clean_text(doc.page_content)
        if not text:
            continue  # blank page (or image-only page): nothing to search
        number = int(doc.metadata.get("page", 0)) + 1
        pages.append(Page(number=number, label=f"page {number}", text=text))
    return pages


def load_docx(path: Path) -> list[Page]:
    """
    DOCX: one Page per section, where a section starts at each heading.

    Word files have no fixed pages (pagination depends on fonts and printer),
    so we use the document's own structure instead: every "Heading" or "Title"
    paragraph starts a new section. Tables are flattened to
    "cell | cell | cell" lines so their content stays searchable.
    """
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise LoadError(f"Could not read DOCX: {exc}") from exc

    # Each section is (heading, lines). The first one has no heading: it
    # collects any text that appears before the first heading.
    sections: list[tuple[str | None, list[str]]] = [(None, [])]

    # Walk the document body in order, so paragraphs and tables stay in reading order.
    for block in document.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]  # strip the XML namespace: "{...}p" -> "p"
        if tag == "p":
            paragraph = Paragraph(block, document)
            text = paragraph.text.strip()
            style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
            if text and (style.startswith("heading") or style == "title"):
                sections.append((text, [text]))  # a heading opens a new section
            elif text:
                sections[-1][1].append(text)
        elif tag == "tbl":
            table = Table(block, document)
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    sections[-1][1].append(" | ".join(cells))
    return _sections_to_pages(sections)


def load_markdown(text: str) -> list[Page]:
    """Markdown: it already marks its structure with '#' headings, so we split on #, ## and ###."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    in_code_block = False
    for line in text.splitlines():
        # Track fenced code blocks: a '#' inside code is a comment, not a heading.
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
        heading = None if in_code_block else re.match(r"^#{1,3}\s+(.+?)\s*#*\s*$", line)
        if heading:
            sections.append((heading.group(1).strip(), [line]))
        else:
            sections[-1][1].append(line)
    return _sections_to_pages(sections)


def load_plain_text(text: str) -> list[Page]:
    """TXT: a .txt file has no structure we can trust, so the whole file becomes a single section."""
    cleaned = clean_text(text)
    return [Page(number=1, label="section 1", text=cleaned)] if cleaned else []


def load_html(html: str) -> tuple[str | None, list[Page]]:
    """
    HTML: keep the article, drop the page furniture. Returns (page title, pages).

    A web page is mostly things that are not content: scripts, menus, footers,
    cookie banners. Indexing those would fill the search results with junk. So
    we remove them, turn h1-h3 headings into Markdown headings, and reuse the
    Markdown sectioning above.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else None

    # Remove the elements that never hold the page's real content.
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe"]):
        tag.decompose()

    # Prefer the main content area. Fall back to the whole body.
    root = soup.find("main") or soup.find("article") or soup.body or soup

    # Rewrite h1-h3 as Markdown headings so load_markdown() can section them.
    for heading in root.find_all(["h1", "h2", "h3"]):
        level = int(heading.name[1])
        heading.replace_with(f"\n\n{'#' * level} {heading.get_text(' ', strip=True)}\n\n")

    # Add a line break after block elements so paragraphs stay separate in the text.
    for block in root.find_all(["p", "li", "pre", "tr", "br", "div"]):
        block.insert_after("\n")
    text = root.get_text("")
    return title, load_markdown(text)


def read_text_file(path: Path) -> str:
    """Decode a text file. Most are UTF-8; Windows-1252 is the usual alternative on Windows."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    # Last resort: decode as UTF-8 and replace the bytes that do not fit.
    return raw.decode("utf-8", errors="replace")


def clean_text(text: str) -> str:
    """
    Normalise whitespace. Extracted text is often full of trailing spaces and
    runs of blank lines. Cleaning it gives the splitter reliable paragraph
    breaks ("\\n\\n") to cut on, and avoids wasting chunk space on whitespace.
    """
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"[ \t]{2,}", " ", text)   # runs of spaces/tabs -> one space
    text = re.sub(r"\n{3,}", "\n\n", text)   # 3+ line breaks -> one blank line
    return text.strip()


def _sections_to_pages(sections: list[tuple[str | None, list[str]]]) -> list[Page]:
    """Turn (heading, lines) sections into numbered Pages, skipping the empty ones."""
    pages: list[Page] = []
    for heading, lines in sections:
        body = lines[1:] if heading else lines  # first line of a headed section is the heading
        if not any(line.strip() for line in body):
            continue  # skip empty sections and headings with no body
        text = clean_text("\n".join(lines))
        number = len(pages) + 1
        label = f"section {number}: {heading[:60]}" if heading else f"section {number}"
        pages.append(Page(number=number, label=label, text=text))
    return pages
