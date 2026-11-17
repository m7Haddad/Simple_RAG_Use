"""Upload validation and SSRF-safe URL fetching."""

import ipaddress
import re
import socket
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from fastapi import UploadFile

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}
READ_CHUNK = 1024 * 1024
MAX_REDIRECTS = 5
USER_AGENT = "LocalRAGStudio/1.0 (+document ingestion)"

CONTENT_TYPE_KINDS = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/x-markdown": "md",
}
EXTENSION_KINDS = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "md", ".markdown": "md", ".html": "html", ".htm": "html"}


class SourceError(Exception):
    """An upload or URL was rejected, or could not be fetched."""

    def __init__(self, message: str, code: str = "invalid_source"):
        super().__init__(message)
        self.code = code
        self.message = message


# --- Uploads -------------------------------------------------------------------


def sanitize_filename(name: str | None) -> str:
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r'[<>:"|?*]', "_", name).strip(" .")
    if len(name) > 120:
        stem, ext = Path(name).stem, Path(name).suffix
        name = stem[: 120 - len(ext)] + ext
    return name or "document"


def check_signature(ext: str, head: bytes) -> None:
    """Make sure the file content matches its extension (a renamed .exe is not a PDF)."""
    if ext == ".pdf" and not head.startswith(b"%PDF-"):
        raise SourceError("File does not look like a PDF", "invalid_file")
    if ext == ".docx" and not head.startswith(b"PK\x03\x04"):
        raise SourceError("File does not look like a DOCX document", "invalid_file")
    if ext in {".txt", ".md", ".markdown"} and b"\x00" in head:
        raise SourceError("File does not look like plain text", "invalid_file")


@dataclass
class SavedUpload:
    display_name: str
    path: Path
    size: int
    content_type: str


async def save_upload(upload: UploadFile, dest_dir: Path, max_bytes: int) -> SavedUpload:
    display_name = sanitize_filename(upload.filename)
    ext = Path(display_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise SourceError(f"{display_name}: unsupported file type (allowed: {allowed})", "unsupported_type")

    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{uuid.uuid4().hex}{ext}"
    size = 0
    try:
        with path.open("wb") as out:
            first = True
            while chunk := await upload.read(READ_CHUNK):
                if first:
                    check_signature(ext, chunk[:1024])
                    first = False
                size += len(chunk)
                if size > max_bytes:
                    raise SourceError(f"{display_name}: file is larger than {max_bytes // (1024 * 1024)} MB", "too_large")
                out.write(chunk)
        if size == 0:
            raise SourceError(f"{display_name}: file is empty", "invalid_file")
    except SourceError as exc:
        path.unlink(missing_ok=True)
        if exc.code == "invalid_file" and not exc.message.startswith(display_name):
            exc.message = f"{display_name}: {exc.message}"
        raise
    return SavedUpload(display_name=display_name, path=path, size=size, content_type=ext.lstrip("."))


# --- URL validation (SSRF protection) ---------------------------------------------


def resolve_host(host: str, port: int) -> list[str]:
    """DNS lookup. Kept as a module function so tests can replace it."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SourceError(f"Could not resolve host {host}", "dns_error") from exc
    return list(dict.fromkeys(info[4][0] for info in infos))


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for globally routable addresses. IPv4 addresses embedded in IPv6 are checked too."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return is_public_ip(ip.ipv4_mapped)
        if ip.sixtofour:
            return is_public_ip(ip.sixtofour)
        if ip.teredo:
            return is_public_ip(ip.teredo[1])
    return ip.is_global and not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


@dataclass
class ValidatedUrl:
    url: str
    scheme: str
    host: str
    port: int
    ip: str
    host_is_ip: bool

    def pinned_url(self) -> str:
        """The same URL, but pointing at the IP we already checked (prevents DNS rebinding)."""
        parts = urlsplit(self.url)
        ip_host = f"[{self.ip}]" if ":" in self.ip else self.ip
        default_port = 443 if self.scheme == "https" else 80
        netloc = ip_host if self.port == default_port else f"{ip_host}:{self.port}"
        return urlunsplit((self.scheme, netloc, parts.path or "/", parts.query, ""))

    def host_header(self) -> str:
        default_port = 443 if self.scheme == "https" else 80
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.port == default_port else f"{host}:{self.port}"


def validate_url(url: str) -> ValidatedUrl:
    """Accept only http(s) URLs whose host resolves to public addresses. Raises SourceError otherwise."""
    url = url.strip()
    if len(url) > 2048:
        raise SourceError("URL is too long", "invalid_url")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise SourceError(f"Only http and https URLs are allowed: {url[:100]}", "invalid_url")
    if parts.username or parts.password:
        raise SourceError("URLs containing credentials are not allowed", "invalid_url")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise SourceError(f"URL has no host: {url[:100]}", "invalid_url")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise SourceError("URL has an invalid port", "invalid_url") from exc

    try:
        literal = ipaddress.ip_address(host)
        addresses, host_is_ip = [str(literal)], True
    except ValueError:
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise SourceError(f"Blocked host {host}: local network addresses are not allowed", "blocked_address")
        addresses, host_is_ip = resolve_host(host, port), False

    if not addresses:
        raise SourceError(f"Could not resolve host {host}", "dns_error")
    for address in addresses:
        if not is_public_ip(ipaddress.ip_address(address.split("%")[0])):
            raise SourceError(
                f"Blocked {host}: it resolves to a private, loopback or reserved address ({address})",
                "blocked_address",
            )
    return ValidatedUrl(url=url, scheme=scheme, host=host, port=port, ip=addresses[0].split("%")[0], host_is_ip=host_is_ip)


# --- Fetching ----------------------------------------------------------------------


@dataclass
class FetchedUrl:
    url: str            # final URL after redirects
    kind: str           # pdf, docx, html, txt, md
    content_type: str
    body: bytes
    encoding: str | None

    def text(self) -> str:
        for encoding in filter(None, [self.encoding, "utf-8"]):
            try:
                return self.body.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return self.body.decode("utf-8", errors="replace")


def classify(content_type: str, url: str) -> str:
    kind = CONTENT_TYPE_KINDS.get(content_type)
    ext = Path(urlsplit(url).path).suffix.lower()
    if kind == "txt" and EXTENSION_KINDS.get(ext) == "md":
        return "md"
    if kind:
        return kind
    if content_type in {"application/octet-stream", "binary/octet-stream", ""} and ext in EXTENSION_KINDS:
        return EXTENSION_KINDS[ext]
    raise SourceError(f"Unsupported content type '{content_type or 'unknown'}'", "unsupported_type")


def fetch_url(url: str, *, max_bytes: int, timeout_s: float, transport: httpx.BaseTransport | None = None) -> FetchedUrl:
    """
    Download a URL safely: every hop (including each redirect) is re-validated,
    the connection goes to the IP we validated, and size and time are capped.
    """
    deadline = time.monotonic() + timeout_s * 2
    timeout = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s))
    current = url
    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            target = validate_url(current)
            extensions = {} if (target.scheme != "https" or target.host_is_ip) else {"sni_hostname": target.host}
            headers = {
                "Host": target.host_header(),
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,text/markdown;q=0.9,*/*;q=0.5",
            }
            try:
                with client.stream("GET", target.pinned_url(), headers=headers, extensions=extensions) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            raise SourceError("Redirect without a Location header", "fetch_error")
                        current = urljoin(current, location)
                        continue
                    if resp.status_code >= 400:
                        raise SourceError(f"Server returned HTTP {resp.status_code}", "fetch_error")

                    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    kind = classify(content_type, current)
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise SourceError(f"Download is larger than {max_bytes // (1024 * 1024)} MB", "too_large")

                    body = bytearray()
                    for chunk in resp.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise SourceError(f"Download is larger than {max_bytes // (1024 * 1024)} MB", "too_large")
                        if time.monotonic() > deadline:
                            raise SourceError("Download took too long", "timeout")
                    return FetchedUrl(url=current, kind=kind, content_type=content_type, body=bytes(body), encoding=resp.charset_encoding)
            except httpx.TimeoutException as exc:
                raise SourceError("Timed out while fetching the URL", "timeout") from exc
            except httpx.HTTPError as exc:
                raise SourceError(f"Could not fetch URL: {exc.__class__.__name__}", "fetch_error") from exc
    raise SourceError(f"Too many redirects (more than {MAX_REDIRECTS})", "fetch_error")
