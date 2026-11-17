"""Test doubles and small utilities shared by the tests."""

import time
import zlib

import numpy as np
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings

from app.rag.retrieval import tokenize


class HashingEmbeddings(Embeddings):
    """Bag-of-words vectors: offline, instant, and texts sharing words are 'similar'."""

    dim = 128

    def __init__(self):
        self.documents_embedded = 0
        self.queries_embedded = 0

    def _vector(self, text: str) -> list[float]:
        v = np.zeros(self.dim)
        for token in tokenize(text):
            v[zlib.crc32(token.encode()) % self.dim] += 1.0
        if not v.any():
            v[0] = 1.0
        return (v / np.linalg.norm(v)).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents_embedded += len(texts)
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries_embedded += 1
        return self._vector(text)


class FakeReranker:
    """Scores by word overlap with the question."""

    def __init__(self, model_name: str):
        self.model_name = model_name

    def score(self, question: str, texts: list[str]) -> list[float]:
        q = set(tokenize(question))
        return [float(len(q & set(tokenize(t)))) for t in texts]


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[str]]) -> bytes:
    """A minimal, valid PDF with one text line per list entry on each page."""
    objects: list[bytes] = []
    font_id = 3 + 2 * len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    for i, lines in enumerate(pages):
        content_id = 4 + 2 * i
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        ops = "BT /F1 11 Tf 14 TL 50 750 Td " + " ".join(f"({_pdf_escape(line)}) Tj T*" for line in lines) + " ET"
        stream = ops.encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def wait_for_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = client.get(f"/ingest/jobs/{job_id}").json()
        if snapshot["stage"] in ("done", "error"):
            return snapshot
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} did not finish")


def parse_sse(text: str) -> list[tuple[str, str]]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        event, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if data:
            events.append((event, "\n".join(data)))
    return events
