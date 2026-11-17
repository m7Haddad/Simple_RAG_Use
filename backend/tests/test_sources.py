import re

import httpx
import pytest

from app import sources
from app.sources import SourceError, fetch_url, sanitize_filename, validate_url

PUBLIC_IP = "93.184.215.14"


@pytest.fixture
def fake_dns(monkeypatch):
    table = {"public.example": [PUBLIC_IP], "evil.example": ["10.0.0.7"], "mixed.example": [PUBLIC_IP, "127.0.0.1"],
             "metadata.example": ["169.254.169.254"]}

    def resolve(host, port):
        if host not in table:
            raise SourceError(f"Could not resolve host {host}", "dns_error")
        return table[host]

    monkeypatch.setattr(sources, "resolve_host", resolve)
    return table


# --- SSRF ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.1.2.3:8000/admin",
        "http://localhost:8000/",
        "http://10.0.0.1/",
        "http://172.16.5.4/",
        "http://192.168.1.10/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fe80::1]/",
        "http://100.64.0.1/",
        "http://224.0.0.1/",
    ],
)
def test_private_and_loopback_addresses_blocked(url):
    with pytest.raises(SourceError) as exc:
        validate_url(url)
    assert exc.value.code == "blocked_address"


@pytest.mark.parametrize("url", ["ftp://public.example/file", "file:///etc/passwd", "gopher://x", "javascript:alert(1)", "http://"])
def test_non_http_schemes_rejected(url, fake_dns):
    with pytest.raises(SourceError):
        validate_url(url)


def test_credentials_in_url_rejected(fake_dns):
    with pytest.raises(SourceError, match="credentials"):
        validate_url("http://user:pass@public.example/")


def test_dns_resolving_to_private_ip_blocked(fake_dns):
    with pytest.raises(SourceError, match="10.0.0.7"):
        validate_url("https://evil.example/page")
    with pytest.raises(SourceError, match="169.254.169.254"):
        validate_url("http://metadata.example/")


def test_any_private_answer_blocks_the_host(fake_dns):
    with pytest.raises(SourceError, match="127.0.0.1"):
        validate_url("https://mixed.example/")


def test_public_host_allowed_and_pinned(fake_dns):
    target = validate_url("https://public.example/docs/page?x=1")
    assert target.ip == PUBLIC_IP
    assert target.pinned_url() == f"https://{PUBLIC_IP}/docs/page?x=1"
    assert target.host_header() == "public.example"


def _transport(routes: dict[str, httpx.Response], seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        key = f"{request.headers['host']}{request.url.raw_path.decode()}"
        return routes.get(key, httpx.Response(404))

    return httpx.MockTransport(handler)


def test_redirect_to_private_ip_blocked(fake_dns):
    seen: list[httpx.Request] = []
    transport = _transport({"public.example/start": httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})}, seen)
    with pytest.raises(SourceError) as exc:
        fetch_url("https://public.example/start", max_bytes=10_000, timeout_s=5, transport=transport)
    assert exc.value.code == "blocked_address"
    assert len(seen) == 1, "the private target must never be requested"


def test_redirect_to_host_resolving_private_blocked(fake_dns):
    seen: list[httpx.Request] = []
    transport = _transport({"public.example/start": httpx.Response(301, headers={"location": "https://evil.example/x"})}, seen)
    with pytest.raises(SourceError, match="10.0.0.7"):
        fetch_url("https://public.example/start", max_bytes=10_000, timeout_s=5, transport=transport)
    assert len(seen) == 1


def test_fetch_connects_to_validated_ip_with_host_header(fake_dns):
    seen: list[httpx.Request] = []
    html = b"<html><head><title>Doc</title></head><body><h1>Hi</h1><p>Hello world</p></body></html>"
    transport = _transport({"public.example/doc": httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=html)}, seen)
    fetched = fetch_url("https://public.example/doc", max_bytes=10_000, timeout_s=5, transport=transport)
    assert fetched.kind == "html"
    assert seen[0].url.host == PUBLIC_IP
    assert seen[0].headers["host"] == "public.example"
    assert seen[0].extensions.get("sni_hostname") == "public.example"


def test_fetch_size_limit(fake_dns):
    seen: list[httpx.Request] = []
    transport = _transport({"public.example/big": httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 5000)}, seen)
    with pytest.raises(SourceError) as exc:
        fetch_url("https://public.example/big", max_bytes=1000, timeout_s=5, transport=transport)
    assert exc.value.code == "too_large"


def test_fetch_rejects_unsupported_content_type(fake_dns):
    seen: list[httpx.Request] = []
    transport = _transport({"public.example/app": httpx.Response(200, headers={"content-type": "application/x-msdownload"}, content=b"MZ")}, seen)
    with pytest.raises(SourceError) as exc:
        fetch_url("https://public.example/app", max_bytes=1000, timeout_s=5, transport=transport)
    assert exc.value.code == "unsupported_type"


def test_too_many_redirects(fake_dns):
    seen: list[httpx.Request] = []
    transport = _transport({"public.example/loop": httpx.Response(302, headers={"location": "/loop"})}, seen)
    with pytest.raises(SourceError, match="Too many redirects"):
        fetch_url("https://public.example/loop", max_bytes=1000, timeout_s=5, transport=transport)


# --- Uploads ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\me\\notes.md", "notes.md"),
        ("bad\x00name\x1f.pdf", "badname.pdf"),
        ('what<>:"|?*.txt', "what_______.txt"),
        ("", "document"),
        ("  .hidden.  ", "hidden"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_upload_rejects_disallowed_extension(client):
    response = client.post("/collections", data={"name": "x"}, files=[("files", ("run.exe", b"MZ...", "application/octet-stream"))])
    assert response.status_code == 422
    assert "unsupported file type" in response.json()["error"]["message"]
    assert client.get("/collections").json() == []


def test_upload_rejects_fake_pdf(client):
    response = client.post("/collections", data={"name": "x"}, files=[("files", ("report.pdf", b"not really a pdf", "application/pdf"))])
    assert response.status_code == 422
    assert "does not look like a PDF" in response.json()["error"]["message"]


def test_upload_rejects_oversized_file(client):
    big = b"word " * (1024 * 1024 // 5 + 10)  # just over the 1 MB test limit
    response = client.post("/collections", data={"name": "x"}, files=[("files", ("big.txt", big, "text/plain"))])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_large"


def test_upload_requires_a_source(client):
    response = client.post("/collections", data={"name": "empty"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_sources"


def test_upload_rejects_non_http_url(client):
    response = client.post("/collections", data={"name": "x", "urls": ["file:///etc/passwd"]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_url"


def test_upload_stored_under_generated_name(client, config):
    response = client.post("/collections", data={"name": "Names"}, files=[("files", ("../../secret notes.txt", b"hello there, plain text", "text/plain"))])
    assert response.status_code == 202, response.text
    collection_id = response.json()["collection"]["id"]
    stored = list((config.data_dir / "collections" / collection_id / "uploads").iterdir())
    assert len(stored) == 1
    assert re.fullmatch(r"[0-9a-f]{32}\.txt", stored[0].name)


def test_private_url_fails_per_source_without_losing_others(client):
    from .helpers import wait_for_job

    response = client.post(
        "/collections",
        data={"name": "Mixed", "urls": ["http://127.0.0.1:8000/secret"]},
        files=[("files", ("ok.txt", b"Plain text about storage tiers and blobs.", "text/plain"))],
    )
    assert response.status_code == 202
    snapshot = wait_for_job(client, response.json()["job"]["job_id"])
    assert snapshot["stage"] == "done"
    statuses = {s["kind"]: s for s in snapshot["sources"]}
    assert statuses["url"]["status"] == "error" and "private" in statuses["url"]["error"]
    assert statuses["file"]["status"] == "indexed"
