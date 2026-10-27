"""HTML/PDF/web text extraction helpers."""
import io

import requests
import trafilatura
from bs4 import BeautifulSoup
from pypdf import PdfReader

UA = {"User-Agent": "Mozilla/5.0 (info-pipeline personal reader)"}


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "img", "table"]):
        tag.decompose()
    lines = (ln.strip() for ln in soup.get_text("\n").splitlines())
    return "\n".join(ln for ln in lines if ln)


def fetch_url_text(url: str, timeout: int = 20) -> tuple[str, str]:
    """Return (title, text) for an article or PDF URL."""
    if url.lower().split("?")[0].endswith(".pdf"):
        resp = requests.get(url, headers=UA, timeout=timeout)
        resp.raise_for_status()
        reader = PdfReader(io.BytesIO(resp.content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:40])
        title = (reader.metadata.title if reader.metadata else None) or url.rsplit("/", 1)[-1]
        return title, text

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise RuntimeError(f"Could not download {url}")
    text = trafilatura.extract(downloaded, include_comments=False) or ""
    meta = trafilatura.extract_metadata(downloaded)
    title = (meta.title if meta and meta.title else url)
    return title, text
