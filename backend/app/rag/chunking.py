"""
STEP 2: SPLIT. Cut each page into chunks small enough to search precisely.

Why we split at all:
  We will later turn every chunk into ONE vector (one "meaning fingerprint").
  A whole 30-page document squeezed into one vector is a blurry average of
  everything in it, so it matches every question a little and none of them
  well. Small chunks give sharp fingerprints. They are also what we paste into
  the prompt, and the LLM's context window is limited.

The two knobs (both measured in CHARACTERS, not tokens):
  chunk_size     The maximum length of a chunk.
                 Small (~300-500): precise matches, but each chunk may lack
                 the surrounding context needed to answer.
                 Large (~2000-3000): more context per chunk, but the vector
                 gets blurrier, and k chunks may overflow the prompt.
  chunk_overlap  How many characters each chunk repeats from the end of the
                 previous one. Without overlap, a sentence that straddles a
                 cut is split in half and neither half matches well. Too much
                 overlap stores the same text many times and returns
                 near-duplicate chunks. It must be smaller than chunk_size.

How RecursiveCharacterTextSplitter cuts:
  It tries the separators in order: blank line (paragraph) -> line break ->
  sentence end -> space -> any character. It only falls back to a "worse"
  separator when a piece is still bigger than chunk_size, so chunks end on
  natural boundaries whenever possible.

Optional heading-aware mode:
  First split the page into sections at headings ("## Install", "2.1 Virtual
  networks", "NETWORKING"), then run the recursive splitter inside each
  section. A chunk then never mixes the end of one topic with the start of the
  next, and every chunk records the heading it belongs to.
"""

import re

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .loading import Page

# Split points tried in order: paragraph, line, sentence, word, character.
SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

# Allowed chunk_size range, in characters.
CHUNK_SIZE_MIN, CHUNK_SIZE_MAX = 200, 4000


def validate_chunk_params(chunk_size: int, chunk_overlap: int) -> None:
    """Reject chunk settings that are out of range, or whose overlap is not smaller than the size."""
    if not CHUNK_SIZE_MIN <= chunk_size <= CHUNK_SIZE_MAX:
        raise ValueError(f"chunk_size must be between {CHUNK_SIZE_MIN} and {CHUNK_SIZE_MAX}")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap must be at least 0 and smaller than chunk_size")


def split_pages(
    pages: list[Page],
    *,
    source_id: str,
    source_name: str,
    chunk_size: int,
    chunk_overlap: int,
    heading_aware: bool = False,
    first_chunk_id: int = 0,
) -> list[Document]:
    """
    Split one source's pages into chunks. Every chunk keeps metadata saying
    where it came from (source, page, character offset), so that later we
    can cite it as "file X, page N".

    Pages are split one at a time and never merged, so a chunk always belongs
    to exactly one page. `first_chunk_id` lets several sources share one
    index: each source continues the numbering where the previous one stopped.
    """
    validate_chunk_params(chunk_size, chunk_overlap)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=SEPARATORS,
        add_start_index=True,  # remember each chunk's character offset within its page
    )

    chunks: list[Document] = []
    current_heading: str | None = None  # a section can continue onto the next PDF page
    for page in pages:
        # Heading-aware mode cuts the page into sections first. Otherwise the
        # whole page is treated as one section with no heading.
        if heading_aware:
            sections, current_heading = split_into_sections(page.text, current_heading)
        else:
            sections = [(None, page.text)]

        for heading, section_text in sections:
            # Metadata shared by every chunk cut from this section.
            base = {
                "source_id": source_id,
                "source_name": source_name,
                "page": page.number,
                "location": page.label,
            }
            if heading:
                base["heading"] = heading
            # Cut the section, then give each chunk its id and size.
            for piece in splitter.create_documents([section_text], metadatas=[base]):
                piece.metadata["chunk_id"] = first_chunk_id + len(chunks)
                piece.metadata["chars"] = len(piece.page_content)
                chunks.append(piece)
    return chunks


# --- Heading detection -----------------------------------------------------
# Markdown headings are explicit. PDFs only give us text, so we guess:
# a short line that is numbered like "2.1 Storage" or written in ALL CAPS
# is probably a heading. A wrong guess only means a slightly different cut.

# Markdown headings such as "## Install".
_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+\S")
# Numbered headings such as "2.1 Storage".
_NUMBERED_HEADING = re.compile(r"^(\d+(\.\d+)+\.?|\d+)\s+[A-Z][^.!?]*$")
_MIN_SECTION_CHARS = 40  # merge tiny sections (a heading on its own) into the next one


def looks_like_heading(line: str) -> bool:
    """Heuristic: is this single line probably a heading?"""
    line = line.strip()
    if not line or len(line) > 80:
        return False
    if _MARKDOWN_HEADING.match(line):
        return True
    if line.endswith((".", ",", ";")):
        return False  # headings rarely end like a sentence
    words = line.split()
    if _NUMBERED_HEADING.match(line) and len(words) <= 10:
        return True
    # A short line written entirely in capitals, such as "NETWORKING BASICS".
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 4 and line.isupper() and len(words) <= 8


def split_into_sections(text: str, current_heading: str | None) -> tuple[list[tuple[str | None, str]], str | None]:
    """
    Break one page's text into sections at its headings.

    Returns [(heading, section_text), ...] plus the heading that is still
    open at the end of the page. The caller passes that heading back in for
    the next page, because a section often runs across a page break.
    """
    # Start with a section under the heading carried over from the previous page.
    sections: list[tuple[str | None, list[str]]] = [(current_heading, [])]
    for line in text.split("\n"):
        if looks_like_heading(line) and "".join(sections[-1][1]).strip():
            # A heading after some text: close the current section, open a new one.
            heading = line.strip().lstrip("#").strip()
            sections.append((heading, [line]))
        elif looks_like_heading(line):
            # The current section is still empty: just rename it.
            sections[-1] = (line.strip().lstrip("#").strip(), sections[-1][1] + [line])
        else:
            sections[-1][1].append(line)

    # Merge tiny sections (for example a lone heading) into the section after
    # them. `carry` holds the text waiting to be merged.
    merged: list[tuple[str | None, str]] = []
    carry = ""
    for heading, lines in sections:
        body = (carry + "\n" + "\n".join(lines)).strip() if carry else "\n".join(lines).strip()
        if len(body) < _MIN_SECTION_CHARS:
            carry = body
            continue
        carry = ""
        if body:
            merged.append((heading, body))

    # A tiny section at the very end has no "next" section: attach it to the last one.
    if carry:
        if merged:
            last_heading, last_body = merged[-1]
            merged[-1] = (last_heading, last_body + "\n" + carry)
        else:
            merged.append((sections[-1][0], carry))
    return merged, sections[-1][0]
