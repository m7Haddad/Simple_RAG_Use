import pytest

from app.rag.chunking import looks_like_heading, split_pages, validate_chunk_params
from app.rag.loading import Page, load_markdown

LONG_TEXT = " ".join(f"Sentence number {i} talks about storage accounts and networking." for i in range(120))


def _split(text: str, size: int, overlap: int, **kw):
    return split_pages([Page(1, "page 1", text)], source_id="s1", source_name="doc.pdf", chunk_size=size, chunk_overlap=overlap, **kw)


def test_chunks_respect_chunk_size():
    chunks = _split(LONG_TEXT, 500, 50)
    assert len(chunks) > 5
    assert all(len(c.page_content) <= 500 for c in chunks)


def test_overlap_repeats_text_between_neighbours():
    chunks = _split(LONG_TEXT, 400, 120)
    shared = 0
    for prev, nxt in zip(chunks, chunks[1:]):
        prev_start = prev.metadata["start_index"]
        nxt_start = nxt.metadata["start_index"]
        assert nxt_start < prev_start + len(prev.page_content), "next chunk should start inside the previous one"
        shared += 1
    assert shared == len(chunks) - 1


def test_zero_overlap_does_not_repeat_text():
    chunks = _split(LONG_TEXT, 400, 0)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.metadata["start_index"] >= prev.metadata["start_index"] + len(prev.page_content)


@pytest.mark.parametrize(
    ("size", "overlap"),
    [(500, 500), (500, 600), (500, -1), (199, 0), (4001, 0)],
)
def test_invalid_chunk_params_rejected(size, overlap):
    with pytest.raises(ValueError):
        validate_chunk_params(size, overlap)


def test_metadata_keeps_page_and_sequential_ids():
    pages = [Page(1, "page 1", LONG_TEXT[:900]), Page(2, "page 2", LONG_TEXT[:900])]
    chunks = split_pages(pages, source_id="abc", source_name="notes.pdf", chunk_size=300, chunk_overlap=30, first_chunk_id=10)
    assert [c.metadata["chunk_id"] for c in chunks] == list(range(10, 10 + len(chunks)))
    assert {c.metadata["page"] for c in chunks} == {1, 2}
    assert all(c.metadata["source_name"] == "notes.pdf" for c in chunks)
    assert chunks[-1].metadata["location"] == "page 2"


def test_heading_aware_splits_at_headings():
    text = (
        "1 Introduction\nThis part explains what the course covers in general terms.\n"
        "2.1 Storage Accounts\nStorage accounts hold blobs, files, queues and tables for apps.\n"
        "NETWORKING BASICS\nVirtual networks connect resources privately inside a region.\n"
    )
    plain = _split(text, 1000, 0)
    aware = _split(text, 1000, 0, heading_aware=True)
    assert len(plain) == 1
    assert [c.metadata["heading"] for c in aware] == ["1 Introduction", "2.1 Storage Accounts", "NETWORKING BASICS"]
    assert aware[1].page_content.startswith("2.1 Storage Accounts")


def test_heading_detection():
    assert looks_like_heading("## Pricing")
    assert looks_like_heading("3.2 Network Security Groups")
    assert looks_like_heading("VIRTUAL MACHINES")
    assert not looks_like_heading("This is a normal sentence that ends with a period.")
    assert not looks_like_heading("1. Click the button.")


def test_markdown_sections_become_pages():
    pages = load_markdown("Intro text here.\n\n# Install\nRun pip install.\n\n## Configure\nEdit the .env file.\n")
    assert [p.label for p in pages] == ["section 1", "section 2: Install", "section 3: Configure"]


def test_docx_sections_and_tables(tmp_path):
    import docx

    from app.rag.loading import load_file

    document = docx.Document()
    document.add_paragraph("Intro paragraph before any heading.")
    document.add_heading("Storage", level=1)
    document.add_paragraph("Blob storage keeps unstructured data.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Tier"
    table.rows[0].cells[1].text = "Archive"
    document.add_heading("Networking", level=2)
    document.add_paragraph("Virtual networks isolate resources.")
    path = tmp_path / "notes.docx"
    document.save(path)

    pages = load_file(path)
    assert [p.label for p in pages] == ["section 1", "section 2: Storage", "section 3: Networking"]
    assert "Tier | Archive" in pages[1].text
