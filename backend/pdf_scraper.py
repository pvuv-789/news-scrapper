"""
Simple PDF Scraper
------------------
Usage:
    python pdf_scraper.py <url>

Examples:
    python pdf_scraper.py https://example.com/report.pdf        # direct PDF
    python pdf_scraper.py https://example.com/reports/          # webpage with PDF links
"""
import asyncio
import io
import sys
import uuid
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
import pdfplumber
from bs4 import BeautifulSoup
from sqlalchemy import select

from core.database import AsyncSessionFactory
from models.db_models import Article, Edition, Publication

# Uses the same seed publication
PUBLICATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── PDF helpers ────────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, str, int]:
    """
    Extract title, full text, and word count from PDF bytes.
    Returns (title, body_text, word_count).
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages_text = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text.strip())

    full_text = "\n\n".join(pages_text)
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

    # Use first non-empty line as title
    title = lines[0][:512] if lines else "Untitled PDF"
    word_count = len(full_text.split())

    return title, full_text, word_count


def make_summary(text: str, max_chars: int = 500) -> str:
    """Return first max_chars characters as a summary."""
    return text[:max_chars].rsplit(" ", 1)[0] + "..." if len(text) > max_chars else text


def is_pdf_url(url: str) -> bool:
    return url.lower().endswith(".pdf") or "application/pdf" in url.lower()


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def fetch_pdf_links_from_page(html: str, base_url: str) -> list[str]:
    """Find all PDF links on an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    pdf_links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        full_url = urljoin(base_url, href)
        if is_pdf_url(full_url):
            pdf_links.append(full_url)
    return list(dict.fromkeys(pdf_links))  # deduplicate


# ── Database helpers ───────────────────────────────────────────────────────────

async def get_edition_id() -> uuid.UUID | None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Edition).where(
                Edition.publication_id == PUBLICATION_ID,
                Edition.is_active == True,
            )
        )
        edition = result.scalars().first()
        return edition.id if edition else None


async def url_already_saved(url: str) -> bool:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Article).where(Article.url == url)
        )
        return result.scalar_one_or_none() is not None


async def save_article(
    title: str,
    summary: str,
    full_text: str,
    url: str,
    word_count: int,
    edition_id: uuid.UUID | None,
    page_number: int = 1,
) -> None:
    async with AsyncSessionFactory() as session:
        article = Article(
            publication_id=PUBLICATION_ID,
            edition_id=edition_id,
            title=title,
            summary=summary,
            url=url,
            word_count_estimate=word_count,
            page_number=page_number,
            published_at=datetime.now(timezone.utc),
            is_active=True,
            is_duplicate=False,
        )
        session.add(article)
        await session.commit()


# ── Main logic ─────────────────────────────────────────────────────────────────

async def scrape_pdf(pdf_url: str, edition_id: uuid.UUID | None, index: int = 1) -> bool:
    """Download, extract, and save a single PDF."""
    print(f"  Downloading: {pdf_url}")

    if await url_already_saved(pdf_url):
        print(f"  Skipped (already in DB): {pdf_url}")
        return False

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        response = await client.get(pdf_url)
        if response.status_code != 200:
            print(f"  Failed ({response.status_code}): {pdf_url}")
            return False

        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type and not is_pdf_url(pdf_url):
            print(f"  Not a PDF (content-type: {content_type})")
            return False

        pdf_bytes = response.content

    try:
        title, full_text, word_count = extract_text_from_pdf(pdf_bytes)
    except Exception as e:
        print(f"  Failed to extract text: {e}")
        return False

    if not full_text.strip():
        print(f"  No text extracted (possibly scanned image PDF): {pdf_url}")
        return False

    summary = make_summary(full_text)

    await save_article(
        title=title,
        summary=summary,
        full_text=full_text,
        url=pdf_url,
        word_count=word_count,
        edition_id=edition_id,
        page_number=index,
    )
    print(f"  Saved: {title[:80]}")
    return True


async def main(target_url: str) -> None:
    print(f"\nTarget: {target_url}")

    edition_id = await get_edition_id()
    if not edition_id:
        print("No edition found. Run seed.py first.")
        return

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        response = await client.get(target_url)
        content_type = response.headers.get("content-type", "")

    # Direct PDF
    if "pdf" in content_type or is_pdf_url(target_url):
        print("Detected: direct PDF URL")
        saved = await scrape_pdf(target_url, edition_id)
        print(f"\n{'✅ Saved' if saved else '⚠️ Not saved'}: {target_url}")
        return

    # Webpage — find PDF links
    print("Detected: webpage. Searching for PDF links...")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        response = await client.get(target_url)

    pdf_links = fetch_pdf_links_from_page(response.text, target_url)

    if not pdf_links:
        print("No PDF links found on this page.")
        return

    print(f"Found {len(pdf_links)} PDF link(s):")
    for link in pdf_links:
        print(f"  {link}")

    saved_count = 0
    for i, pdf_url in enumerate(pdf_links, start=1):
        success = await scrape_pdf(pdf_url, edition_id, index=i)
        if success:
            saved_count += 1

    print(f"\n✅ Done. Saved {saved_count}/{len(pdf_links)} PDFs to database.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdf_scraper.py <url>")
        print("Example: python pdf_scraper.py https://example.com/report.pdf")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
