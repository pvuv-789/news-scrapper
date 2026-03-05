"""
Scrape routes:
  POST /scrape/pdf           — download PDFs from URL, extract text, save as articles
  POST /scrape/webpage-pdf   — login to epaper, render page with Playwright, return PDF download
"""
import asyncio
import io
import os
import re
import uuid
from datetime import date as _date
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
import pdfplumber
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from core.config import get_settings

from core.database import AsyncSessionFactory
from models.db_models import Article, Edition

router = APIRouter(prefix="/scrape", tags=["scrape"])

PUBLICATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Tamil-capable TTF font pairs: (regular, bold)
# fpdf2 needs each style registered separately via add_font()
_TAMIL_FONT_PAIRS: list[tuple[str, str | None]] = [
    (r"C:\Windows\Fonts\Nirmala.ttf",  r"C:\Windows\Fonts\NirmalaB.ttf"),   # Windows 8+
    (r"C:\Windows\Fonts\latha.ttf",    r"C:\Windows\Fonts\lathab.ttf"),     # Windows XP+
    ("/usr/share/fonts/truetype/lohit-tamil/Lohit-Tamil.ttf",        None),
    ("/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf",     None),
]


def _find_tamil_font() -> tuple[str, str | None] | None:
    """
    Return (regular_path, bold_path_or_None) for the first available Tamil font pair,
    or None if no Tamil font is found on this system.
    """
    for regular, bold in _TAMIL_FONT_PAIRS:
        if os.path.isfile(regular):
            bold_path = bold if bold and os.path.isfile(bold) else None
            return (regular, bold_path)
    return None


# ── Schemas ────────────────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str


class ScrapeResultItem(BaseModel):
    url: str
    title: str
    status: str  # "saved" | "skipped" | "failed"
    message: str = ""


class ScrapeResponse(BaseModel):
    total_found: int
    saved: int
    skipped: int
    failed: int
    results: list[ScrapeResultItem]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_pdf_url(url: str) -> bool:
    return url.lower().endswith(".pdf")


def _extract_pdf_text(pdf_bytes: bytes) -> tuple[str, str, int]:
    """Returns (title, summary, word_count)."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages_text = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text.strip())

    full_text = "\n\n".join(pages_text)
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]
    title = lines[0][:512] if lines else "Untitled PDF"
    summary = full_text[:500].rsplit(" ", 1)[0] + "..." if len(full_text) > 500 else full_text
    word_count = len(full_text.split())
    return title, summary, word_count


def _find_pdf_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for tag in soup.find_all("a", href=True):
        full = urljoin(base_url, tag["href"])
        if _is_pdf_url(full):
            links.append(full)
    return list(dict.fromkeys(links))


async def _get_edition_id() -> uuid.UUID | None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Edition).where(
                Edition.publication_id == PUBLICATION_ID,
                Edition.is_active == True,
            )
        )
        edition = result.scalars().first()
        return edition.id if edition else None


async def _url_exists(url: str) -> bool:
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Article).where(Article.url == url))
        return result.scalar_one_or_none() is not None


async def _save_article(title: str, summary: str, url: str, word_count: int, edition_id: uuid.UUID | None, page_number: int) -> None:
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


async def _process_pdf(pdf_url: str, edition_id: uuid.UUID | None, index: int) -> ScrapeResultItem:
    if await _url_exists(pdf_url):
        return ScrapeResultItem(url=pdf_url, title="", status="skipped", message="Already in database")

    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
            response = await client.get(pdf_url)

        if response.status_code != 200:
            return ScrapeResultItem(url=pdf_url, title="", status="failed", message=f"HTTP {response.status_code}")

        title, summary, word_count = _extract_pdf_text(response.content)

        if not summary.strip():
            return ScrapeResultItem(url=pdf_url, title=title, status="failed", message="No text extracted (scanned PDF?)")

        await _save_article(title, summary, pdf_url, word_count, edition_id, index)
        return ScrapeResultItem(url=pdf_url, title=title, status="saved", message=f"{word_count} words extracted")

    except Exception as e:
        return ScrapeResultItem(url=pdf_url, title="", status="failed", message=str(e)[:200])


# ── Route ──────────────────────────────────────────────────────────────────────

@router.post("/pdf", response_model=ScrapeResponse)
async def scrape_pdf(body: ScrapeRequest):
    """
    Scrape PDFs from a URL.
    - If the URL is a direct PDF: download and extract it.
    - If the URL is a webpage: find all PDF links and extract each one.
    """
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    edition_id = await _get_edition_id()
    pdf_urls: list[str] = []

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        try:
            response = await client.get(url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {e}")

        content_type = response.headers.get("content-type", "")

    if "pdf" in content_type or _is_pdf_url(url):
        pdf_urls = [url]
    else:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
            response = await client.get(url)
        pdf_urls = _find_pdf_links(response.text, url)

    if not pdf_urls:
        return ScrapeResponse(total_found=0, saved=0, skipped=0, failed=0, results=[])

    results = []
    for i, pdf_url in enumerate(pdf_urls, start=1):
        result = await _process_pdf(pdf_url, edition_id, i)
        results.append(result)

    saved = sum(1 for r in results if r.status == "saved")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")

    return ScrapeResponse(
        total_found=len(pdf_urls),
        saved=saved,
        skipped=skipped,
        failed=failed,
        results=results,
    )


# ── Webpage → PDF route ────────────────────────────────────────────────────────

class WebpagePdfRequest(BaseModel):
    url: str


async def _do_login(page, settings) -> bool:
    """Login to Daily Thanthi epaper. Returns True if login succeeded."""
    base_url = settings.epaper_base_url
    await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    # Use JavaScript to find and fill login fields (bypasses visibility issues)
    logged_in = await page.evaluate(f"""
        () => {{
            // Try to find login inputs by common selectors
            const emailSelectors = ['#txtUserName', '#txtEmail', 'input[name="UserName"]', 'input[type="email"]'];
            const passSelectors  = ['#txtPassword', 'input[name="Password"]', 'input[type="password"]'];
            const btnSelectors   = ['#btnLogin', 'input[type="submit"]', 'button[type="submit"]'];

            let emailEl = null, passEl = null, btnEl = null;

            for (const s of emailSelectors) {{
                emailEl = document.querySelector(s);
                if (emailEl) break;
            }}
            for (const s of passSelectors) {{
                passEl = document.querySelector(s);
                if (passEl) break;
            }}
            for (const s of btnSelectors) {{
                btnEl = document.querySelector(s);
                if (btnEl) break;
            }}

            if (emailEl && passEl) {{
                // Make visible if hidden
                emailEl.style.display = 'block';
                passEl.style.display  = 'block';
                emailEl.value = '{settings.epaper_email}';
                passEl.value  = '{settings.epaper_password}';

                // Trigger input events so the JS validation picks up the values
                emailEl.dispatchEvent(new Event('input', {{bubbles: true}}));
                passEl.dispatchEvent(new Event('input', {{bubbles: true}}));

                if (btnEl) {{
                    btnEl.style.display = 'block';
                    btnEl.click();
                    return true;
                }}
            }}
            return false;
        }}
    """)

    if logged_in:
        await page.wait_for_timeout(4000)

    # If JS approach didn't work, try clicking visible login trigger
    if not logged_in:
        for trigger in ["a:has-text('Login')", "a:has-text('Sign In')", "#loginBtn", ".signin"]:
            try:
                el = await page.query_selector(trigger)
                if el:
                    await el.click()
                    await page.wait_for_timeout(2000)
                    # Now fill fields
                    for email_sel in ["#txtUserName", "#txtEmail", "input[type='email']"]:
                        try:
                            e = await page.query_selector(email_sel)
                            p_el = await page.query_selector("input[type='password']")
                            if e and p_el:
                                await e.fill(settings.epaper_email)
                                await p_el.fill(settings.epaper_password)
                                # Submit
                                for btn in ["#btnLogin", "button[type='submit']"]:
                                    b = await page.query_selector(btn)
                                    if b:
                                        await b.click()
                                        await page.wait_for_timeout(4000)
                                        return True
                        except Exception:
                            pass
                    break
            except Exception:
                pass

    return True  # proceed regardless and let the navigation reveal if login worked


async def _extract_articles_from_page(page) -> list[dict]:
    """Extract all articles from the ArticleView page by clicking each rectangle."""
    articles = []

    # Get all pagerectangle elements with storyid
    rects = await page.query_selector_all(".pagerectangle[storyid]")
    if not rects:
        return articles

    for rect in rects:
        try:
            story_id = await rect.get_attribute("storyid")
            await rect.click()
            await page.wait_for_timeout(2000)

            headline = await page.eval_on_selector("#divheadline", "el => el.innerText.trim()") if await page.query_selector("#divheadline") else ""
            byline   = await page.eval_on_selector("#byline",      "el => el.innerText.trim()") if await page.query_selector("#byline") else ""
            dateline = await page.eval_on_selector("#DateLine",    "el => el.innerText.trim()") if await page.query_selector("#DateLine") else ""
            body     = await page.eval_on_selector("#body",        "el => el.innerText.trim()") if await page.query_selector("#body") else ""

            if headline or body:
                articles.append({
                    "story_id": story_id,
                    "headline": headline,
                    "byline":   byline,
                    "dateline": dateline,
                    "body":     body,
                })
        except Exception:
            continue

    return articles


def _build_pdf_from_articles(
    articles: list[dict],
    page_url: str,
    edate: str,
    screenshots: list[dict] | None = None,
) -> bytes:
    """
    Build a clean text PDF from extracted article data.
    • screenshots (optional): list of {"label": str, "png": bytes} — newspaper page images
      embedded as full-width images before the article text.
    • Uses a Tamil-capable TTF font (Nirmala/Latha on Windows) so Tamil Unicode
      text is rendered correctly instead of being replaced with '?'.
    """
    import io as _io
    import struct as _struct
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_margins(left=15, top=15, right=15)
    pdf.set_auto_page_break(auto=True, margin=15)

    # ── Font setup ─────────────────────────────────────────────────────────────
    _font_pair = _find_tamil_font()
    _fname = None
    _has_bold = False
    if _font_pair:
        regular_path, bold_path = _font_pair
        try:
            pdf.add_font("TamilFont", fname=regular_path)
            if bold_path:
                pdf.add_font("TamilFont", style="B", fname=bold_path)
                _has_bold = True
            else:
                pdf.add_font("TamilFont", style="B", fname=regular_path)
                _has_bold = True
            _fname = "TamilFont"
        except Exception:
            _fname = None

    def _sf(size: int, bold: bool = False) -> None:
        if _fname:
            pdf.set_font(_fname, style="B" if (bold and _has_bold) else "", size=size)
        else:
            pdf.set_font("Helvetica", style="B" if bold else "", size=size)

    def _rt(text: str) -> str:
        return text if _fname else _safe_text(text)

    # ── Cover page ─────────────────────────────────────────────────────────────
    pdf.add_page()
    pw = pdf.epw

    _sf(20, bold=True)
    pdf.set_text_color(20, 30, 80)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pw, 12, "Daily Thanthi E-Paper", align="C")
    _sf(12)
    pdf.set_text_color(60, 60, 60)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pw, 8, f"Date: {edate}", align="C")
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pw, 8, f"Source:", align="C")
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pw, 8, f"{page_url}", align="C")
    pdf.ln(10)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pw, pdf.get_y())
    pdf.ln(6)

    # ── Newspaper page screenshots ─────────────────────────────────────────────
    if screenshots:
        _sf(13, bold=True)
        pdf.set_text_color(20, 30, 80)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pw, 9, f"Newspaper Pages ({len(screenshots)} pages captured)", align="C")
        pdf.ln(4)

        for shot in screenshots:
            try:
                img_bytes: bytes = shot["png"]   # PNG or JPEG both supported
                label: str = shot.get("label", "Page")

                _sf(9)
                pdf.set_text_color(80, 80, 80)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(pw, 6, _rt(label), align="C")
                pdf.set_x(pdf.l_margin)
                # fpdf2 auto-computes height from width keeping aspect ratio
                # Works for both PNG and JPEG natively
                pdf.image(_io.BytesIO(img_bytes), x=pdf.l_margin, w=pw)
                pdf.ln(6)
                pdf.add_page()
            except Exception:
                pass

    # ── Article text ───────────────────────────────────────────────────────────
    _sf(16, bold=True)
    pdf.set_text_color(20, 30, 80)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pw, 10, f"Article Content ({len(articles)} articles)", align="C")
    pdf.ln(4)
    pdf.set_draw_color(60, 100, 200)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pw, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(6)

    if not articles:
        _sf(12)
        pdf.set_text_color(120, 60, 60)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(
            pw, 10,
            "No article text could be extracted.\n"
            "This page may be an advertisement or the login/API call failed.\n"
            "Check the backend logs for [DT] diagnostics.",
            align="C",
        )
    else:
        for i, article in enumerate(articles, 1):
            try:
                if article.get("headline"):
                    pdf.set_x(pdf.l_margin)
                    _sf(14, bold=True)
                    pdf.set_text_color(20, 40, 120)
                    pdf.multi_cell(pw, 8, _rt(article["headline"]))
                    pdf.set_text_color(0, 0, 0)
                    pdf.ln(2)

                meta = " | ".join(filter(None, [article.get("byline"), article.get("dateline")]))
                if meta:
                    pdf.set_x(pdf.l_margin)
                    _sf(9)
                    pdf.set_text_color(100, 100, 100)
                    pdf.multi_cell(pw, 6, _rt(meta))
                    pdf.set_text_color(0, 0, 0)
                    pdf.ln(2)

                if article.get("body"):
                    pdf.set_x(pdf.l_margin)
                    _sf(11)
                    pdf.set_text_color(40, 40, 40)
                    pdf.multi_cell(pw, 7, _rt(article["body"]))
                    pdf.set_text_color(0, 0, 0)

                pdf.ln(6)
                if i < len(articles):
                    pdf.set_draw_color(220, 220, 220)
                    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pw, pdf.get_y())
                    pdf.ln(6)

            except Exception:
                pdf.set_x(pdf.l_margin)
                _sf(9)
                pdf.set_text_color(150, 150, 150)
                pdf.multi_cell(pw, 6, f"[Article {i}: could not be rendered]")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(4)

    return bytes(pdf.output())


def _safe_text(text: str) -> str:
    """Remove characters that fpdf can't encode in latin-1."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


@router.post("/webpage-pdf")
async def scrape_webpage_to_pdf(body: WebpagePdfRequest):
    """
    Daily Thanthi epaper scraper:
    - If URL is the homepage (epaper.dailythanthi.com) → login and scrape today's full edition.
    - If URL is an ArticleView page → login and scrape that specific page's articles.
    Returns a downloadable PDF with Tamil Unicode text preserved.
    """
    from urllib.parse import parse_qs as _pqs

    settings = get_settings()
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # ── Path A: Homepage → scrape today's full edition ────────────────────────
    if _is_dailythanthi_homepage(url):
        try:
            result = await asyncio.to_thread(
                _scrape_epaper_today_sync,
                settings.epaper_email,
                settings.epaper_password,
                settings.epaper_base_url,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Scrape error: {str(e)[:300]}")

        articles_data = result["articles"]
        edate = result["edition"]["date"]

        try:
            pdf_bytes = _build_pdf_from_articles(articles_data, url, edate)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)[:200]}")

        edate_safe = edate.replace("/", "-")
        filename = f"dailythanthi_{edate_safe}_today.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── Path B: Specific ArticleView page ─────────────────────────────────────
    qs    = _pqs(urlparse(url).query)
    edate = qs.get("edate", [""])[0]
    eid   = qs.get("eid",   [""])[0]

    try:
        scrape_result = await asyncio.to_thread(
            _scrape_dailythanthi_sync,
            url,
            settings.epaper_email,
            settings.epaper_password,
            settings.epaper_base_url,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Page render error: {str(e)[:300]}")

    articles_data = scrape_result.get("articles", [])
    screenshots   = scrape_result.get("screenshots", [])
    edate         = scrape_result.get("edate", "") or edate  # prefer freshly parsed value

    # Save to database
    if articles_data:
        for i, art in enumerate(articles_data, 1):
            article_url = f"{url}&storyid={art.get('story_id', i)}"
            if not await _url_exists(article_url):
                title   = art.get("headline") or "Untitled"
                summary = (art.get("body") or "")[:500]
                wc      = len((art.get("body") or "").split())
                await _save_article(title, summary, article_url, wc, await _get_edition_id(), i)

    try:
        pdf_bytes = _build_pdf_from_articles(articles_data, url, edate, screenshots)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)[:200]}")

    edate_safe = edate.replace("/", "-") if edate else "page"
    filename = f"dailythanthi_{edate_safe}_eid{eid}.pdf" if eid else "dailythanthi_page.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── URL → PDF (scrape any public webpage) ─────────────────────────────────────

class UrlToPdfRequest(BaseModel):
    url: str


def _scrape_any_url_sync(url: str) -> dict:
    """
    Use sync_playwright to render any public webpage (JS-heavy or static)
    and extract structured content. Run via asyncio.to_thread() — safe on Windows.
    """
    from playwright.sync_api import sync_playwright

    html = ""
    final_url = url
    page_title = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        try:
            # networkidle waits for all AJAX/fetch to settle
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            # Fall back if networkidle times out (e.g. long-polling pages)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
            except Exception:
                pass

        html = page.content()        # fully rendered HTML with JS applied
        final_url = page.url         # follow any redirects
        page_title = page.title()
        browser.close()

    # Parse the rendered HTML with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "nav", "footer", "aside", "iframe"]):
        tag.decompose()

    # Title — prefer browser title (most accurate after JS runs)
    title = page_title or ""
    if not title and soup.find("h1"):
        title = soup.find("h1").get_text(strip=True)
    if not title:
        title = urlparse(url).netloc

    # Meta description
    meta_desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta:
        meta_desc = meta.get("content", "").strip()

    # Published date (common meta tag patterns)
    published = ""
    for attr in ["article:published_time", "datePublished", "pubdate", "date"]:
        tag = soup.find("meta", attrs={"property": attr}) or soup.find("meta", attrs={"name": attr})
        if tag:
            published = tag.get("content", "").strip()
            if published:
                break
    if not published:
        time_tag = soup.find("time", attrs={"datetime": True})
        if time_tag:
            published = time_tag["datetime"].strip()

    # Content blocks — prefer <main>/<article> over full <body>
    content_blocks = []
    main = soup.find("main") or soup.find("article") or soup.find("body")
    if main:
        for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
            text = el.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            if not text or len(text) < 8:
                continue
            content_blocks.append({"tag": el.name, "text": text})

    # Links (up to 40)
    links: list[dict] = []
    seen_hrefs: set[str] = set()
    for a in soup.find_all("a", href=True):
        label = a.get_text(strip=True)
        href = a["href"]
        if not href.startswith("http"):
            href = urljoin(final_url, href)
        if href.startswith("http") and label and href not in seen_hrefs:
            seen_hrefs.add(href)
            links.append({"label": label[:100], "href": href})
        if len(links) >= 40:
            break

    return {
        "title": title,
        "url": url,
        "meta_description": meta_desc,
        "published": published,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "content_blocks": content_blocks,
        "links": links,
    }


def _build_url_pdf(data: dict) -> bytes:
    """Build a formatted PDF from scraped webpage data."""
    from fpdf import FPDF

    class _PDF(FPDF):
        def header(self):
            self.set_x(self.l_margin)
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(130, 130, 130)
            self.cell(self.epw, 8, "Web Scraper Report", align="L")
            self.ln(5)
            self.set_draw_color(210, 210, 210)
            self.line(self.l_margin, self.get_y(), self.l_margin + self.epw, self.get_y())
            self.ln(4)

        def footer(self):
            self.set_y(-15)
            self.set_x(self.l_margin)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(160, 160, 160)
            self.cell(self.epw, 10, f"Page {self.page_no()}", align="C")

    pdf = _PDF()
    pdf.set_margins(left=15, top=15, right=15)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    pw = pdf.epw  # effective page width

    # Title
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(20, 30, 80)
    pdf.multi_cell(pw, 10, _safe_text(data["title"] or "Web Page Report"))
    pdf.ln(4)

    # Meta info rows — label cell + value multi_cell
    info_rows = [("URL", data["url"]), ("Scraped at", data["scraped_at"])]
    if data.get("published"):
        info_rows.append(("Published", data["published"]))
    if data.get("meta_description"):
        info_rows.append(("Description", data["meta_description"]))

    label_w = 32
    for label, value in info_rows:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(label_w, 7, f"{label}:")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(40, 40, 40)
        pdf.multi_cell(pw - label_w, 7, _safe_text(value))

    pdf.ln(4)
    pdf.set_draw_color(60, 100, 200)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pw, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(6)

    HEADING_SIZES = {"h1": 16, "h2": 14, "h3": 12, "h4": 11}
    for block in data["content_blocks"]:
        tag = block["tag"]
        text = _safe_text(block["text"])

        try:
            pdf.set_x(pdf.l_margin)
            if tag in HEADING_SIZES:
                pdf.set_font("Helvetica", "B", HEADING_SIZES[tag])
                pdf.set_text_color(20, 40, 120)
                pdf.ln(3)
                pdf.multi_cell(pw, 8, text)
                pdf.ln(1)
            elif tag == "blockquote":
                pdf.set_font("Helvetica", "I", 10)
                pdf.set_text_color(80, 80, 80)
                pdf.set_fill_color(240, 240, 250)
                pdf.multi_cell(pw, 7, f'"{text}"', fill=True)
                pdf.ln(2)
            elif tag == "li":
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(40, 40, 40)
                pdf.multi_cell(pw, 6, f"  \u2022 {text}")
            else:
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(40, 40, 40)
                pdf.multi_cell(pw, 6, text)
                pdf.ln(2)
        except Exception:
            continue  # skip blocks that can't render

    if data["links"]:
        pdf.add_page()
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(20, 40, 120)
        pdf.cell(pw, 10, "Links Found on Page", ln=True)
        pdf.ln(2)
        for i, lnk in enumerate(data["links"], start=1):
            try:
                pdf.set_x(pdf.l_margin)
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_text_color(50, 50, 50)
                pdf.multi_cell(pw, 5, f"{i}. {_safe_text(lnk['label'])}")
                pdf.set_x(pdf.l_margin)
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(0, 80, 180)
                pdf.multi_cell(pw, 5, f"   {lnk['href']}")
                pdf.ln(1)
            except Exception:
                continue

    return bytes(pdf.output())


def _is_dailythanthi_article(url: str) -> bool:
    return "epaper.dailythanthi.com" in url and "ArticleView" in url


def _is_dailythanthi_homepage(url: str) -> bool:
    """True for the main epaper site URL (not a specific ArticleView page)."""
    return "epaper.dailythanthi.com" in url and "ArticleView" not in url


def _render_url_to_pdf_sync(url: str) -> bytes:
    """
    Render any public webpage as a full-page screenshot and embed it in a PDF.

    Uses Playwright's screenshot(full_page=True) so every pixel of the rendered
    page is captured — images, CSS, fonts, dynamic content — exactly as the
    browser shows it.  The PNG is then placed on a custom-sized PDF page
    (A4-width, height scaled to match the full screenshot) so nothing is cropped.

    Safe to call inside asyncio.to_thread() on Windows.
    """
    import struct
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # Wait for JS/AJAX to settle before screenshotting
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
            except Exception:
                pass

        # Extra pause for lazy-loaded images / web-fonts
        page.wait_for_timeout(2000)

        # Capture the ENTIRE page (scrolls down automatically)
        png_bytes = page.screenshot(full_page=True)
        browser.close()

    # Parse PNG dimensions from the IHDR chunk (bytes 16–23) — no PIL needed
    w_px = struct.unpack(">I", png_bytes[16:20])[0]
    h_px = struct.unpack(">I", png_bytes[20:24])[0]

    # Scale to A4 width (210 mm), stretch page height to hold full screenshot
    A4_W_MM = 210.0
    scale = A4_W_MM / w_px        # mm per pixel
    page_h_mm = h_px * scale      # custom tall page, no cropping

    from fpdf import FPDF
    pdf = FPDF(unit="mm", format=(A4_W_MM, page_h_mm))
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.image(io.BytesIO(png_bytes), x=0, y=0, w=A4_W_MM, h=page_h_mm)

    return bytes(pdf.output())


# ── API-interception helpers ───────────────────────────────────────────────────
# The ArticleView page loads article content via an internal API:
#   getstorydetail?Storyid=XXXXXXX  →  { StoryContent: [{ Headlines: [...], Body: "<html>" }] }
# We intercept these responses directly instead of reading from the DOM.

def _extract_storyid(api_url: str) -> str:
    """Extract the Storyid value from a getstorydetail request URL."""
    from urllib.parse import parse_qs
    qs = parse_qs(urlparse(api_url).query)
    # The param name is 'Storyid' (capital S) but handle both cases
    return (qs.get("Storyid") or qs.get("storyid") or [""])[0]


def _parse_story_response(data: dict, api_url: str, output: list[dict]) -> None:
    """
    Parse one getstorydetail JSON response and append article dicts to output.

    JSON shape (from DevTools):
        {
          "StoryContent": [{ "Headlines": ["...","..."], "Body": "<p>...</p>" }],
          "EditionName": "Kanchipuram",
          ...
        }

    Python's json() decoder automatically converts \u003c → < so Tamil
    Unicode text in the Body is preserved perfectly without extra work.
    """
    edition = data.get("EditionName", "")
    story_id = _extract_storyid(api_url)

    for story in data.get("StoryContent", []):
        headlines: list[str] = [h.strip() for h in story.get("Headlines", []) if h and h.strip()]
        body_html: str = story.get("Body", "") or ""

        # Strip HTML tags from Body → clean plain text (Tamil chars preserved)
        soup = BeautifulSoup(body_html, "html.parser")
        body_text = soup.get_text(separator="\n", strip=True)
        body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip()

        headline = headlines[0] if headlines else ""
        sub_heads = " | ".join(headlines[1:]) if len(headlines) > 1 else ""

        if headline or body_text:
            output.append({
                "headline": headline,
                "byline":   sub_heads,
                "dateline": edition,
                "body":     body_text,
                "story_id": story_id,
            })


# ── Sync Playwright helpers (Windows-safe) ────────────────────────────────────
# asyncio.create_subprocess_exec is NOT supported on Windows SelectorEventLoop.
# Running sync_playwright inside asyncio.to_thread() avoids the issue entirely.

_LOGIN_JS_TEMPLATE = """
() => {{
    const emailSels = ['#txtUserName','#txtEmail','input[name="UserName"]','input[type="email"]'];
    const passSels  = ['#txtPassword','input[name="Password"]','input[type="password"]'];
    const btnSels   = ['#btnLogin','input[type="submit"]','button[type="submit"]'];
    let e=null, pw=null, btn=null;
    for (const s of emailSels) {{ e = document.querySelector(s); if (e) break; }}
    for (const s of passSels)  {{ pw = document.querySelector(s); if (pw) break; }}
    for (const s of btnSels)   {{ btn = document.querySelector(s); if (btn) break; }}
    if (e && pw) {{
        e.style.display = 'block'; pw.style.display = 'block';
        e.value = '{email}'; pw.value = '{password}';
        e.dispatchEvent(new Event('input', {{bubbles:true}}));
        pw.dispatchEvent(new Event('input', {{bubbles:true}}));
        if (btn) {{ btn.style.display='block'; btn.click(); return true; }}
    }}
    return false;
}}
"""


def _fill_visible_login_form(page, email: str, password: str, log) -> bool:
    """
    Fill and submit the login form using a generic JavaScript approach.

    Instead of guessing selectors, we:
      1. Log every <input> on the page so we know exactly what's there.
      2. Find the password field (type=password) and the first non-password
         non-hidden text-type field (the username/email box) in JS — works
         regardless of id/name/type attribute on the email field.
      3. Use the native HTMLInputElement value setter so React/Angular
         controlled inputs pick up the new value.
      4. Dispatch input+change events, then click the submit button.
    """
    # ── Dump all inputs so the log shows us exactly what's on the page ──────
    try:
        inputs_info = page.evaluate("""
            () => Array.from(document.querySelectorAll('input')).map(i => ({
                id: i.id || '',
                name: i.name || '',
                type: i.type,
                placeholder: i.placeholder || '',
                vis: window.getComputedStyle(i).display !== 'none'
            }))
        """)
        log.info(f"[DT-LOGIN] Inputs on page: {inputs_info}")
    except Exception as ex:
        log.warning(f"[DT-LOGIN] Could not enumerate inputs: {ex}")

    # ── Generic JS fill — no hard-coded selectors ────────────────────────────
    try:
        result = page.evaluate(
            """([emailVal, passVal]) => {
                // Find password field
                const all = Array.from(document.querySelectorAll('input'));
                const passEl = all.find(i => i.type === 'password');
                if (!passEl) return 'NO_PASS';

                // Find the username/email field:
                // first visible non-password, non-hidden, non-button input
                const SKIP = ['hidden','submit','button','checkbox','radio','file','image','reset'];
                const emailEl = all.find(i => i !== passEl && !SKIP.includes(i.type));
                if (!emailEl) return 'NO_EMAIL';

                // Native value setter bypasses React/Angular controlled-input wrappers
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(emailEl, emailVal);
                setter.call(passEl,  passVal);

                // Fire input + change so the framework picks up the values
                ['input', 'change'].forEach(ev => {
                    emailEl.dispatchEvent(new Event(ev, {bubbles: true}));
                    passEl.dispatchEvent(new Event(ev, {bubbles: true}));
                });

                // Submit
                const form = passEl.closest('form');
                const btn = form && (
                    form.querySelector('#btnLogin')              ||
                    form.querySelector('[type="submit"]')        ||
                    form.querySelector('button[type="submit"]')  ||
                    form.querySelector('button')
                );
                if (btn) {
                    btn.click();
                    return 'CLICKED:' + (btn.id || btn.textContent.trim().slice(0, 20));
                }
                if (form) { form.submit(); return 'FORM_SUBMIT'; }
                return 'NO_SUBMIT';
            }""",
            [email, password],
        )
        log.info(f"[DT-LOGIN] JS fill result: {result!r}")
        if result in ("NO_PASS", "NO_EMAIL"):
            log.error(f"[DT-LOGIN] Could not find form fields via JS: {result}")
            return False
        return True
    except Exception as ex:
        log.error(f"[DT-LOGIN] JS fill exception: {ex}")
        return False


def _dismiss_already_logged_in_dialog(page, log) -> bool:
    """
    After login form submission, Daily Thanthi may show a modal dialog:
    'You are already logged in on other device. If you continue this login,
    you will be logged out from previous session.' — automatically click YES.
    Polls for up to 4 seconds. Returns True if the dialog was found and dismissed.
    """
    for _ in range(8):  # 8 × 500 ms = 4 seconds
        try:
            result = page.evaluate("""
                () => {
                    const body = document.body ? document.body.innerText : '';
                    if (!body.includes('already logged in') && !body.includes('logged out from previous')) {
                        return null;
                    }
                    const candidates = Array.from(document.querySelectorAll(
                        'button, input[type="button"], input[type="submit"], a'
                    ));
                    const yesEl = candidates.find(el => {
                        const txt = (el.textContent || el.value || '').trim();
                        return txt === 'Yes' && window.getComputedStyle(el).display !== 'none';
                    });
                    if (yesEl) { yesEl.click(); return 'CLICKED_YES'; }
                    return 'MSG_VISIBLE_NO_BTN';
                }
            """)
            if result == 'CLICKED_YES':
                log.info("[DT-LOGIN] 'Already logged in on other device' dialog dismissed — clicked Yes")
                page.wait_for_timeout(1500)
                return True
            if result == 'MSG_VISIBLE_NO_BTN':
                log.warning("[DT-LOGIN] Dialog visible but Yes button not found yet")
        except Exception as ex:
            log.warning(f"[DT-LOGIN] Dialog check error: {ex}")
        page.wait_for_timeout(500)
    return False


def _navigate_and_login(page, url: str, email: str, password: str, log) -> bool:
    """
    Navigate to url (redirects to login if unauthenticated), fill the login form,
    wait for redirect back, and wait for networkidle. Returns True if on a non-login page.
    """
    log.info(f"[DT] Navigating to: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as err:
        log.warning(f"[DT] goto warning: {err}")
    page.wait_for_timeout(2000)
    log.info(f"[DT] URL after goto: {page.url!r}")

    if "login" in page.url.lower() or "landingpage" in page.url.lower():
        log.info("[DT] On login page — filling form")
        if not _fill_visible_login_form(page, email, password, log):
            log.error("[DT] Login form submission failed")
            return False
        _dismiss_already_logged_in_dialog(page, log)
        try:
            page.wait_for_url("*ArticleView*", timeout=20000)
            log.info(f"[DT] Redirected to: {page.url!r}")
        except Exception:
            log.warning(f"[DT] wait_for_url timeout, url={page.url!r}")

        # After login, server redirects to the default first page.
        # Navigate explicitly to the originally requested URL (specific pgid).
        if page.url.rstrip("/") != url.rstrip("/"):
            log.info(f"[DT] Re-navigating to requested pgid URL: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as err:
                log.warning(f"[DT] Re-navigation warning: {err}")
            page.wait_for_timeout(2000)

    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(2000)
    log.info(f"[DT] Final URL: {page.url!r}")
    return "login" not in page.url.lower() and "landingpage" not in page.url.lower()


def _scrape_page_articles(page, log, api_base_holder: dict | None = None) -> list[dict]:
    """
    Extract all articles from a loaded ArticleView page.

    Primary strategy - httpx API calls:
      Collect story IDs from [storyid] rectangle elements, then call the
      getstorydetail API directly using browser session cookies. This is more
      reliable than DOM reading because it doesn't depend on right-panel selectors.

    Fallback strategy - DOM reading:
      If httpx yields nothing, click each rect and read #divheadline / #body
      from the live DOM.
    """
    if api_base_holder is None:
        api_base_holder = {"url": ""}

    articles: list[dict] = []

    # Register request listener to capture the getstorydetail API base URL
    def _on_request(req: object) -> None:
        try:
            url_str: str = req.url  # type: ignore[attr-defined]
            if "getstorydetail" in url_str.lower() and not api_base_holder['url']:
                parsed = urlparse(url_str)
                api_base_holder['url'] = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                log.info(f"[DT] API base captured: {api_base_holder['url']}")
        except Exception:
            pass

    page.on("request", _on_request)

    # Find [storyid] rectangle elements (try multiple attribute casings)
    rects = []
    for attr_name in ("storyid", "StoryId", "data-storyid"):
        try:
            page.wait_for_selector(f"[{attr_name}]", timeout=12000)
            rects = page.query_selector_all(f"[{attr_name}]")
            if rects:
                log.info(f"[DT] {len(rects)} rects with [{attr_name}]")
                break
        except Exception:
            pass

    if not rects:
        log.warning("[DT] No [storyid] rects — advertisement-only page or login failed")
        return articles

    # Collect unique story IDs (no clicking yet)
    seen_sids: set[str] = set()
    story_ids: list[str] = []
    for rect in rects:
        try:
            sid = (
                rect.get_attribute("storyid")
                or rect.get_attribute("StoryId")
                or rect.get_attribute("data-storyid")
                or ""
            ).strip()
            if sid and sid not in seen_sids:
                seen_sids.add(sid)
                story_ids.append(sid)
        except Exception:
            pass

    log.info(f"[DT] Collected {len(story_ids)} unique story IDs")

    # Build API base URL — captured from network OR guessed
    if not api_base_holder['url']:
        parsed_page = urlparse(page.url)
        api_base_holder['url'] = f"{parsed_page.scheme}://{parsed_page.netloc}/Home/getstorydetail"
        log.info(f"[DT] Guessed API base: {api_base_holder['url']}")

    # ── PRIMARY: httpx direct API calls ──────────────────────────────────────
    try:
        cookies_dict = {c["name"]: c["value"] for c in page.context.cookies()}
        hdrs = {
            "User-Agent": HEADERS["User-Agent"],
            "Referer": page.url,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        with httpx.Client(
            cookies=cookies_dict, headers=hdrs,
            follow_redirects=True, timeout=20,
        ) as client:
            for sid in story_ids:
                api_url = f"{api_base_holder['url']}?Storyid={sid}"
                try:
                    resp = client.get(api_url)
                    log.info(f"[DT] httpx {sid}: status={resp.status_code}")
                    if resp.status_code == 200:
                        before = len(articles)
                        _parse_story_response(resp.json(), api_url, articles)
                        log.info(f"[DT] httpx parsed {sid}: +{len(articles) - before}")
                except Exception as ex:
                    log.warning(f"[DT] httpx error {sid}: {ex}")
    except Exception as ex:
        log.error(f"[DT] httpx session error: {ex}")

    log.info(f"[DT] httpx extracted {len(articles)} articles from {len(story_ids)} stories")

    if articles:
        return articles

    # ── FALLBACK: click each rect and read right-panel DOM ───────────────────
    log.warning("[DT] httpx returned nothing — trying DOM click fallback")

    def _dom(selector: str, timeout_ms: int = 2000) -> str:
        try:
            return (page.inner_text(selector, timeout=timeout_ms) or "").strip()
        except Exception:
            return ""

    dom_articles: list[dict] = []
    for rect in rects:
        try:
            sid = (
                rect.get_attribute("storyid")
                or rect.get_attribute("StoryId")
                or rect.get_attribute("data-storyid")
                or ""
            ).strip()
            if not sid:
                continue

            rect.click()
            page.wait_for_timeout(1500)

            headline = (
                _dom("#divheadline") or _dom("#headline")
                or _dom(".article-headline") or _dom("h1")
            )
            body = (
                _dom("#body") or _dom("#articleBody") or _dom("#storyBody")
                or _dom(".article-body") or _dom(".story-content")
            )
            byline   = _dom("#byline")   or _dom(".byline")
            dateline = _dom("#DateLine") or _dom(".dateline")

            log.info(f"[DT] DOM sid={sid} head={headline[:60]!r} body_len={len(body)}")

            if headline or body:
                dom_articles.append({
                    "story_id": sid,
                    "headline": headline,
                    "byline":   byline,
                    "dateline": dateline,
                    "body":     body,
                })
        except Exception as ex:
            log.debug(f"[DT] DOM click error sid={sid}: {ex}")

    log.info(f"[DT] DOM fallback extracted {len(dom_articles)} articles")
    return dom_articles


def _find_sidebar_pages(page, current_url: str, log) -> list[dict]:
    """
    Collect all ArticleView page links for the current edition.

    Tries 4 strategies in order:
      1. <a href*="ArticleView"> with pgid  (standard links)
      2. [data-pgid] / [data-pageid] attributes
      3. onclick="...pgid=NNN..." or onclick="loadPage(NNN)"
      4. img[src*="pgid"] thumbnail images (pre-loaded page previews)

    Returns list of {"url": str, "label": str, "pgid": str}.
    """
    from urllib.parse import urlparse as _up, parse_qs as _pqs

    try:
        cur_pgid = _pqs(_up(current_url).query).get("pgid", [""])[0]

        raw = page.evaluate(
            """([currentUrl, currentPgid]) => {
                const seen   = new Set([currentUrl]);
                const pages  = [];

                function addPgid(pgid, label) {
                    if (!pgid || !/^\\d+$/.test(pgid)) return;
                    if (pgid === currentPgid) return;
                    try {
                        const u = new URL(currentUrl);
                        u.searchParams.set('pgid', pgid);
                        const href = u.toString();
                        if (!seen.has(href)) {
                            seen.add(href);
                            pages.push({ href, label: (label || '').trim() || 'pgid-' + pgid, pgid });
                        }
                    } catch(_) {}
                }

                // Strategy 1 — <a href> links (pgid OR PageId OR pageid)
                document.querySelectorAll('a[href*="ArticleView"],a[href*="pgid="],a[href*="PageId="],a[href*="pageid="]').forEach(a => {
                    try {
                        const u   = new URL(a.href, location.origin);
                        const pid = u.searchParams.get('pgid')
                                 || u.searchParams.get('PageId')
                                 || u.searchParams.get('pageid')
                                 || u.searchParams.get('page_id');
                        if (pid && /^\\d+$/.test(pid) && !seen.has(a.href)) {
                            seen.add(a.href);
                            const sp = a.querySelector('span,.pagename,.page-name,p');
                            pages.push({ href: a.href,
                                         label: ((sp || a).textContent || '').trim() || 'pgid-' + pid,
                                         pgid: pid });
                        }
                    } catch(_) {}
                });

                if (pages.length > 0) return pages;

                // Strategy 2 — data-pgid / data-pageid / data-PageId
                document.querySelectorAll('[data-pgid],[data-pageid],[data-PageId],[data-page_id]').forEach(el => {
                    const pid = el.getAttribute('data-pgid')
                             || el.getAttribute('data-pageid')
                             || el.getAttribute('data-PageId')
                             || el.getAttribute('data-page_id');
                    addPgid(pid, el.textContent);
                });

                // Strategy 3 — onclick handlers
                document.querySelectorAll('[onclick]').forEach(el => {
                    const oc = el.getAttribute('onclick') || '';
                    // matches: loadPage('123'), loadPage(123), pgid=123, pgid:'123'
                    const m  = oc.match(/loadPage\\s*\\(['"\\s]*(\\d+)/i)
                            || oc.match(/pgid['"\\s:=]+(\\d+)/i);
                    if (m) addPgid(m[1], el.textContent);
                });

                if (pages.length > 0) return pages;

                // Strategy 4 — thumbnail img[src*="pgid"] or img[src*="pageid"]
                document.querySelectorAll('img[src*="pgid"],img[src*="pageid"],img[src*="PageId"]').forEach(img => {
                    try {
                        const u   = new URL(img.src, location.origin);
                        const pid = u.searchParams.get('pgid')
                                 || u.searchParams.get('pageid')
                                 || u.searchParams.get('PageId');
                        if (pid) {
                            const container = img.closest('[onclick],[data-pgid],a') || img.parentElement;
                            addPgid(pid, container ? container.textContent : '');
                        }
                    } catch(_) {}
                });

                return pages;
            }""",
            [current_url, cur_pgid],
        )

        # Deduplicate by pgid
        seen_pgids: set[str] = {cur_pgid}
        result: list[dict] = []
        for item in raw:
            pgid = item.get("pgid", "")
            if pgid and pgid not in seen_pgids:
                seen_pgids.add(pgid)
                result.append({"url": item["href"], "label": item.get("label", ""), "pgid": pgid})

        log.info(f"[DT-SIDEBAR] Found {len(result)} sidebar pages")
        return result

    except Exception as ex:
        log.warning(f"[DT-SIDEBAR] Error: {ex}")
        return []


def _scrape_dailythanthi_sync(url: str, email: str, password: str, base_url: str) -> dict:
    """
    Login to Daily Thanthi epaper and extract ALL articles from the given
    ArticleView page PLUS every other page found in the sidebar.

    Returns:
        {
            "articles":    list[dict],   # all extracted articles
            "screenshots": list[dict],   # [{"label": str, "png": bytes}, ...]
            "edate":       str,          # edition date string
        }

    Key changes vs original:
    - page.on("request") registered BEFORE _navigate_and_login so auto-load
      getstorydetail XHRs are captured (not just click-triggered ones).
    - After login, a viewport screenshot is taken of each newspaper page.
    - All sidebar pages (news 1 .. news N) are scraped automatically.
    """
    import logging
    from urllib.parse import parse_qs as _pqs
    from playwright.sync_api import sync_playwright

    log = logging.getLogger(__name__)
    result: dict = {"articles": [], "screenshots": [], "edate": ""}

    # Parse edate from the requested URL
    qs = _pqs(urlparse(url).query)
    result["edate"] = qs.get("edate", [""])[0]

    # Shared API base holder — written by _on_request, read by _scrape_page_articles
    api_base_holder: dict = {"url": ""}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # Register request listener BEFORE navigation so auto-load XHRs are captured
        def _capture_api_base(req) -> None:
            try:
                if "getstorydetail" in req.url.lower() and not api_base_holder['url']:
                    parsed = urlparse(req.url)
                    api_base_holder['url'] = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    log.info(f"[DT-SYNC] API base: {api_base_holder['url']}")
            except Exception:
                pass

        page.on("request", _capture_api_base)

        ok = _navigate_and_login(page, url, email, password, log)
        if not ok:
            log.error("[DT-SYNC] Still on login page - aborting")
            browser.close()
            return result

        # Capture screenshot of this page (viewport, not full-page, to show the newspaper)
        def _take_shot(label: str) -> None:
            try:
                png = page.screenshot(full_page=False)
                result["screenshots"].append({"label": label, "png": png})
                log.info(f"[DT-SYNC] Screenshot: {label!r}  ({len(png)} bytes)")
            except Exception as ex:
                log.warning(f"[DT-SYNC] Screenshot failed for {label!r}: {ex}")

        _take_shot(f"Page pgid={qs.get('pgid', ['?'])[0]}")

        # Extract articles from this first page
        first_articles = _scrape_page_articles(page, log, api_base_holder)
        result["articles"].extend(first_articles)
        log.info(f"[DT-SYNC] First page articles: {len(first_articles)}")

        # Find other pages in the sidebar and scrape them
        sidebar_pages = _find_sidebar_pages(page, url, log)
        log.info(f"[DT-SYNC] Sidebar pages found: {len(sidebar_pages)}")

        seen_pgids: set[str] = {qs.get("pgid", [""])[0]}
        seen_heads: set[str] = {a.get("headline", "") for a in result["articles"]}

        for pg_info in sidebar_pages[:10]:  # max 10 additional pages
            pgid = pg_info.get("pgid", "")
            if pgid and pgid in seen_pgids:
                continue
            if pgid:
                seen_pgids.add(pgid)

            other_url = pg_info["url"]
            pg_label  = pg_info.get("label") or f"pgid-{pgid}"
            log.info(f"[DT-SYNC] Navigating to sidebar page: {other_url}")

            try:
                page.goto(other_url, wait_until="domcontentloaded", timeout=20000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)

                _take_shot(pg_label)

                pg_articles = _scrape_page_articles(page, log, api_base_holder)
                for art in pg_articles:
                    h = art.get("headline", "")
                    if h not in seen_heads:
                        result["articles"].append(art)
                        if h:
                            seen_heads.add(h)

            except Exception as ex:
                log.warning(f"[DT-SYNC] Sidebar page error: {ex}")

        browser.close()

    log.info(
        f"[DT-SYNC] Done: {len(result['articles'])} articles  "
        f"{len(result['screenshots'])} screenshots"
    )
    return result


def _scrape_epaper_today_sync(email: str, password: str, base_url: str) -> dict:
    """
    Login to Daily Thanthi epaper, find today's ArticleView pages, and extract
    all articles using page.route() interception + rectangle clicks.

    Returns {"edition": {date, pages_scraped, total_articles}, "articles": [...]}.
    Safe to call inside asyncio.to_thread() on Windows.
    """
    import logging
    from playwright.sync_api import sync_playwright

    log = logging.getLogger(__name__)

    today_str     = _date.today().strftime("%d/%m/%Y")
    today_encoded = today_str.replace("/", "%2F")

    all_articles: list[dict] = []
    seen_heads:   set[str]   = set()
    edition_info = {"date": today_str, "pages_scraped": 0, "total_articles": 0}

    # Use the login landing page directly — form is always visible there
    first_av_url = base_url.rstrip("/") + "/Login/Landingpage"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # ── Login ───────────────────────────────────────────────────────────────
        log.info(f"[DT-TODAY] Loading login page: {first_av_url}")
        try:
            page.goto(first_av_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as err:
            log.warning(f"[DT-TODAY] Login page warning: {err}")
        page.wait_for_timeout(2000)

        submitted = _fill_visible_login_form(page, email, password, log)
        if not submitted:
            log.error("[DT-TODAY] Login failed")
            browser.close()
            return {"edition": edition_info, "articles": all_articles}

        _dismiss_already_logged_in_dialog(page, log)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        log.info(f"[DT-TODAY] URL after login: {page.url!r}")

        # ── Find today's ArticleView links ─────────────────────────────────────
        article_view_urls: list[str] = page.evaluate(f"""
            () => {{
                const links = Array.from(document.querySelectorAll('a[href*="ArticleView"]'));
                const filtered = links
                    .map(a => a.href)
                    .filter(h => h.includes('{today_str}') || h.includes('{today_encoded}'));
                return [...new Set(filtered)];
            }}
        """)
        if not article_view_urls:
            article_view_urls = page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a[href*="ArticleView"]'))
                        .map(a => a.href);
                    return [...new Set(links)].slice(0, 8);
                }
            """)
        article_view_urls = article_view_urls[:6]
        log.info(f"[DT-TODAY] ArticleView URLs: {len(article_view_urls)}")

        if not article_view_urls:
            log.error(f"[DT-TODAY] No ArticleView links found. Page title: {page.title()!r}")
            browser.close()
            return {"edition": edition_info, "articles": all_articles}

        # ── Scrape each page using DOM-reading + click strategy ────────────────
        api_base_holder: dict = {"url": ""}

        # Register request listener so API base is captured during navigation
        def _capture_api(req) -> None:
            try:
                if "getstorydetail" in req.url.lower() and not api_base_holder['url']:
                    parsed = urlparse(req.url)
                    api_base_holder['url'] = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            except Exception:
                pass

        page.on("request", _capture_api)

        for av_url in article_view_urls:
            log.info(f"[DT-TODAY] Scraping: {av_url}")
            try:
                page.goto(av_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as err:
                log.warning(f"[DT-TODAY] Navigation warning: {err}")
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(2000)

            page_articles = _scrape_page_articles(page, log, api_base_holder)
            for art in page_articles:
                h = art.get("headline", "")
                if h not in seen_heads:
                    all_articles.append(art)
                    if h:
                        seen_heads.add(h)

            edition_info["pages_scraped"] += 1

        browser.close()

    edition_info["total_articles"] = len(all_articles)
    log.info(f"[DT-TODAY] Done. pages={edition_info['pages_scraped']} articles={len(all_articles)}")
    return {"edition": edition_info, "articles": all_articles}


@router.post("/url-to-pdf")
async def scrape_url_to_pdf(body: UrlToPdfRequest):
    """
    Scrape any public webpage and return a downloadable PDF report.
    Automatically uses Playwright for Daily Thanthi ArticleView URLs,
    and httpx+BeautifulSoup for all other public pages.
    """
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # ── Daily Thanthi homepage → scrape today's full edition ─────────────────
    if _is_dailythanthi_homepage(url):
        settings = get_settings()
        try:
            result = await asyncio.to_thread(
                _scrape_epaper_today_sync,
                settings.epaper_email,
                settings.epaper_password,
                settings.epaper_base_url,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Scrape error: {str(e)[:300]}")

        articles_data = result["articles"]
        edate = result["edition"]["date"]
        try:
            pdf_bytes = _build_pdf_from_articles(articles_data, url, edate)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)[:200]}")

        edate_safe = edate.replace("/", "-")
        filename = f"dailythanthi_{edate_safe}_today.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── Daily Thanthi ArticleView → sync Playwright in thread ────────────────
    if _is_dailythanthi_article(url):
        from urllib.parse import parse_qs as _parse_qs
        settings = get_settings()
        qs = _parse_qs(urlparse(url).query)
        edate = qs.get("edate", [""])[0]
        eid   = qs.get("eid",   [""])[0]

        try:
            scrape_result = await asyncio.to_thread(
                _scrape_dailythanthi_sync,
                url,
                settings.epaper_email,
                settings.epaper_password,
                settings.epaper_base_url,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Page render error: {str(e)[:300]}")

        articles_data = scrape_result.get("articles", [])
        screenshots   = scrape_result.get("screenshots", [])
        edate         = scrape_result.get("edate", "") or edate

        try:
            pdf_bytes = _build_pdf_from_articles(articles_data, url, edate, screenshots)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)[:200]}")

        edate_safe = edate.replace("/", "-") if edate else "page"
        filename = f"dailythanthi_{edate_safe}_eid{eid}.pdf" if eid else "dailythanthi_page.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── General public URL → Playwright page.pdf() (Chrome Print-to-PDF) ────
    # Uses Chromium's built-in print engine so the full rendered page
    # (images, fonts, JS-applied styles) is captured — not just plain text.
    try:
        pdf_bytes = await asyncio.to_thread(_render_url_to_pdf_sync, url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to render URL to PDF: {str(e)[:200]}")

    hostname = urlparse(url).hostname or "page"
    filename = f"scraped_{hostname.replace('.', '_')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Screenshot endpoint ────────────────────────────────────────────────────────

def _screenshot_sync(url: str, email: str | None, password: str | None) -> bytes:
    """Render a page with Playwright and return a full-page PNG screenshot."""
    import logging
    from playwright.sync_api import sync_playwright
    log = logging.getLogger(__name__)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        if email and password and "dailythanthi.com" in url:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            if "login" in page.url.lower() or "landingpage" in page.url.lower():
                _fill_visible_login_form(page, email, password, log)
                _dismiss_already_logged_in_dialog(page, log)
                try:
                    page.wait_for_url("*ArticleView*", timeout=20000)
                except Exception:
                    pass
                try:
                    page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
        else:
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(3000)
                except Exception:
                    pass

        png = page.screenshot(full_page=True)
        browser.close()
    return png


@router.post("/webpage-screenshot")
async def scrape_webpage_screenshot(body: WebpagePdfRequest):
    """Return a full-page PNG screenshot. Daily Thanthi URLs are auto-logged-in."""
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    settings = get_settings()
    e = settings.epaper_email    if "dailythanthi.com" in url else None
    pw = settings.epaper_password if "dailythanthi.com" in url else None

    try:
        png_bytes = await asyncio.to_thread(_screenshot_sync, url, e, pw)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {str(ex)[:300]}")

    hostname = urlparse(url).hostname or "page"
    filename = f"screenshot_{hostname.replace('.', '_')}.png"
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Edition-specific article scraper ─────────────────────────────────────────

class EditionArticlesRequest(BaseModel):
    eid: str
    edition_name: str = ""
    date: str = ""  # DD/MM/YYYY; defaults to today


def _scrape_edition_articles_sync(
    eid: str, edate: str, email: str, password: str, base_url: str
) -> dict:
    """
    Login to Daily Thanthi and scrape ALL pages for a specific edition.

    Root-cause fix: After login the server always redirects to the user's DEFAULT
    edition (Madurai) regardless of the eid= query param.  To get a different
    edition we must CLICK the edition link inside the website's own edition
    selector — exactly what a human user does.

    Flow:
      1. Login via Landingpage (same as a browser user)
      2. Open the edition selector modal / bar
      3. Find the <a> or element whose href/data contains eid={eid} and CLICK it
      4. Wait for the page to load the new edition
      5. Navigate to ArticleView?eid={eid}&edate={edate} for the correct date
      6. Scrape page 1, then all sidebar pages (news 2, news 3 …)

    Returns {"articles": list[dict], "edate": str, "eid": str}
    """
    import logging
    from urllib.parse import parse_qs as _pqs
    from playwright.sync_api import sync_playwright

    log = logging.getLogger(__name__)
    result: dict = {"articles": [], "pages": [], "edate": edate, "eid": eid}

    login_url   = base_url.rstrip("/") + "/Login/Landingpage"
    article_url = f"{base_url.rstrip('/')}/Home/ArticleView?eid={eid}&edate={edate}"
    api_base_holder: dict = {"url": ""}
    pgid_set: set[str] = set()
    pgid_capture_active: dict = {"active": False}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # Capture API base and sidebar pgids from network requests.
        # pgid capture is gated by pgid_capture_active so we only collect pgids
        # from the TARGET edition (not the default Madurai that loads after login).
        def _capture_api(req) -> None:
            try:
                url_str = req.url
                if "getstorydetail" in url_str.lower() and not api_base_holder["url"]:
                    parsed = urlparse(url_str)
                    api_base_holder["url"] = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if pgid_capture_active["active"]:
                    m = re.search(r"[?&](?:pgid|pageid|page_id)=(\d+)", url_str, re.IGNORECASE)
                    if m:
                        pgid_set.add(m.group(1))
            except Exception:
                pass

        page.on("request", _capture_api)

        # ── Step 1: Login via login page ─────────────────────────────────────────
        log.info(f"[DT-EDITION] Loading login page for eid={eid}")
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as err:
            log.warning(f"[DT-EDITION] Login page warning: {err}")
        page.wait_for_timeout(2000)

        submitted = _fill_visible_login_form(page, email, password, log)
        if not submitted:
            log.error("[DT-EDITION] Login form submission failed")
            browser.close()
            return result

        _dismiss_already_logged_in_dialog(page, log)
        try:
            page.wait_for_url("*ArticleView*", timeout=20000)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        log.info(f"[DT-EDITION] Post-login URL: {page.url!r}")

        # ── Step 2: Open the edition selector ────────────────────────────────────
        for sel in [
            "#selectEdition", ".selectEdition", "#editionSelect",
            "[data-target*='edition' i]", "[data-toggle][data-target*='edition' i]",
            "button:has-text('Edition')", "a:has-text('Edition')",
            ".edition-btn", "#editionBtn", ".ed-select",
            ".topnav .edition", ".nav-edition",
            "[id*='edition' i]", "[class*='edition' i]",
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    page.wait_for_timeout(2000)
                    log.info(f"[DT-EDITION] Opened edition selector via: {sel}")
                    break
            except Exception:
                pass

        # ── Step 3: Click the edition link whose href contains eid={eid} ─────────
        clicked = page.evaluate(
            """(targetEid) => {
                // Look for <a href*="eid="> anchors
                for (const a of document.querySelectorAll('a[href*="eid="]')) {
                    try {
                        const u = new URL(a.href, location.origin);
                        if (u.searchParams.get('eid') === targetEid) {
                            a.click();
                            return 'HREF:' + a.href.slice(0, 80);
                        }
                    } catch(_) {}
                }
                // Look for [data-eid] elements
                const byData = document.querySelector('[data-eid="' + targetEid + '"]');
                if (byData) { byData.click(); return 'DATA-EID'; }
                return null;
            }""",
            eid,
        )
        log.info(f"[DT-EDITION] Edition click result: {clicked!r}")

        if clicked:
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            log.info(f"[DT-EDITION] After edition click: {page.url!r}")

        # ── Step 4: Navigate to the specific date for this edition ───────────────
        # Enable pgid capture NOW so sidebar thumbnail requests on the target page
        # are captured (not the default-edition thumbnails loaded right after login).
        pgid_capture_active["active"] = True
        log.info(f"[DT-EDITION] Navigating to: {article_url}")
        try:
            page.goto(article_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as err:
            log.warning(f"[DT-EDITION] Navigation warning: {err}")
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        # Scroll sidebar to trigger lazy-loaded thumbnail XHRs (which carry pgids)
        try:
            page.evaluate("""
                () => {
                    // Target common sidebar selectors first
                    const sidebarSels = [
                        '.page-sidebar', '.sidebar', '#sidebar', '.left-panel',
                        '[class*="sidebar" i]', '[class*="thumbnail" i]',
                        '[class*="page-list" i]', '[class*="pagelist" i]',
                        '[class*="pagethumb" i]', '[class*="page-thumb" i]',
                    ];
                    let scrolled = false;
                    for (const sel of sidebarSels) {
                        try {
                            const el = document.querySelector(sel);
                            if (el && el.scrollHeight > el.clientHeight + 20) {
                                el.scrollTop = el.scrollHeight;
                                scrolled = true;
                            }
                        } catch(_) {}
                    }
                    // Fallback: scroll every overflowing element
                    if (!scrolled) {
                        document.querySelectorAll('*').forEach(el => {
                            try {
                                if (el.scrollHeight > el.clientHeight + 50)
                                    el.scrollTop = el.scrollHeight;
                            } catch(_) {}
                        });
                    }
                }
            """)
            page.wait_for_timeout(2000)
        except Exception:
            pass
        log.info(f"[DT-EDITION] Final URL for eid={eid}: {page.url!r}")
        log.info(f"[DT-EDITION] Network-captured pgids so far: {sorted(pgid_set)}")

        if "login" in page.url.lower() or "landingpage" in page.url.lower():
            log.error(f"[DT-EDITION] Still on login page — aborting eid={eid}")
            browser.close()
            return result

        # ── Step 5: Scrape page 1 ─────────────────────────────────────────────
        import base64 as _b64

        def _take_shot() -> str:
            """Take a JPEG viewport screenshot; return base64 string (empty on error)."""
            try:
                jpg = page.screenshot(full_page=False, type="jpeg", quality=60)
                return _b64.b64encode(jpg).decode("ascii")
            except Exception:
                return ""

        first_articles = _scrape_page_articles(page, log, api_base_holder)
        all_articles: list[dict] = list(first_articles)
        log.info(f"[DT-EDITION] Page 1: {len(first_articles)} articles")

        # ── Build pgid → label map from every <a href*="pgid="> on the page ──
        cur_pgid = _pqs(urlparse(page.url).query).get("pgid", [""])[0]
        pgid_to_label: dict[str, str] = {}
        try:
            all_pg_links: dict = page.evaluate("""
                () => {
                    const m = {};
                    document.querySelectorAll('a[href*="pgid="]').forEach(a => {
                        try {
                            const u = new URL(a.href, location.origin);
                            const p = u.searchParams.get('pgid');
                            if (p && /^\\d+$/.test(p)) {
                                const lbl = (a.textContent || '').trim().replace(/\\s+/g,' ');
                                if (lbl && lbl.length < 60) m[p] = lbl;
                            }
                        } catch(_) {}
                    });
                    return m;
                }
            """) or {}
            pgid_to_label.update(all_pg_links)
        except Exception:
            pass

        # Supplement labels from DOM sidebar helper
        sidebar_info = _find_sidebar_pages(page, page.url, log)
        for sp in sidebar_info:
            if sp.get("pgid") and sp.get("label"):
                pgid_to_label[sp["pgid"]] = sp["label"]

        pg1_label = pgid_to_label.get(cur_pgid, "news 1")
        log.info(f"[DT-EDITION] Page 1 label={pg1_label!r} pgid={cur_pgid}")

        result["pages"].append({
            "pgid": cur_pgid,
            "label": pg1_label,
            "articles": first_articles,
            "screenshot_b64": _take_shot(),
        })

        # ── Step 6: Traverse ALL pages using network-captured pgids ──────────
        seen_pgids: set[str] = {cur_pgid} if cur_pgid else set()
        seen_heads: set[str] = {a.get("headline", "") for a in all_articles}

        # Primary: pgids captured from sidebar thumbnail network requests
        remaining_pgids: list[str] = sorted(pgid_set - seen_pgids)
        log.info(f"[DT-EDITION] Network-captured extra pgids: {remaining_pgids}")

        # Fallback: DOM-based sidebar detection
        if not remaining_pgids:
            remaining_pgids = [
                sp.get("pgid", "")
                for sp in sidebar_info
                if sp.get("pgid") and sp.get("pgid") not in seen_pgids
            ]
            log.info(f"[DT-EDITION] DOM-fallback pgids: {remaining_pgids}")

        base_av_url = f"{base_url.rstrip('/')}/Home/ArticleView"
        edate_enc   = edate.replace("/", "%2F")
        page_num    = 2  # sequential fallback label counter

        for pgid in remaining_pgids[:18]:  # cap at 18 pages (news 1-18)
            if not pgid or pgid in seen_pgids:
                continue
            seen_pgids.add(pgid)

            pg_label = pgid_to_label.get(pgid, f"news {page_num}")
            pg_url   = f"{base_av_url}?eid={eid}&edate={edate_enc}&pgid={pgid}"
            log.info(f"[DT-EDITION] Navigating to pgid={pgid} ({pg_label!r})")
            try:
                page.goto(pg_url, wait_until="domcontentloaded", timeout=20000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)

                pg_arts  = _scrape_page_articles(page, log, api_base_holder)
                new_arts: list[dict] = []
                for art in pg_arts:
                    h = art.get("headline", "")
                    if h not in seen_heads:
                        all_articles.append(art)
                        new_arts.append(art)
                        if h:
                            seen_heads.add(h)

                result["pages"].append({
                    "pgid": pgid,
                    "label": pg_label,
                    "articles": new_arts,
                    "screenshot_b64": _take_shot(),
                })
                log.info(f"[DT-EDITION] pgid={pgid}: {len(pg_arts)} scraped, {len(new_arts)} new")
            except Exception as ex:
                log.warning(f"[DT-EDITION] pgid={pgid} error: {ex}")
            page_num += 1

        result["articles"] = all_articles
        log.info(
            f"[DT-EDITION] Done — {len(all_articles)} articles  "
            f"{len(result['pages'])} pages  eid={eid}"
        )
        browser.close()

    return result


def _discover_editions_sync(email: str, password: str, base_url: str) -> list[dict]:
    """
    Login to Daily Thanthi e-paper and enumerate all available editions.

    Strategy:
    1. Navigate to the login landing page and submit credentials.
    2. Wait for the post-login page to settle.
    3. Try to click the edition selector widget to reveal edition links.
    4. Collect every unique ?eid= value found in anchor href attributes and
       also in elements with a data-eid attribute.

    Returns a sorted list of {"name": str, "eid": str}.
    """
    import logging
    from playwright.sync_api import sync_playwright

    log = logging.getLogger(__name__)
    login_url = base_url.rstrip("/") + "/Login/Landingpage"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as err:
            log.warning(f"[DT-DISCOVER] Login page warning: {err}")
        page.wait_for_timeout(2000)

        _fill_visible_login_form(page, email, password, log)
        _dismiss_already_logged_in_dialog(page, log)

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        log.info(f"[DT-DISCOVER] Post-login URL: {page.url!r}")

        # Try to open the edition selector to reveal all edition links
        for sel in [
            "#selectEdition", ".selectEdition", "#editionSelect",
            "[data-target*='edition' i]", "[data-toggle][data-target*='edition' i]",
            "a:has-text('Edition')", "button:has-text('Edition')",
            ".edition-btn", "#editionBtn", ".ed-select",
        ]:
            try:
                el = page.query_selector(sel)
                if el:
                    el.click()
                    page.wait_for_timeout(2000)
                    log.info(f"[DT-DISCOVER] Clicked edition selector: {sel}")
                    break
            except Exception:
                pass

        # Collect unique eid→name entries from anchor hrefs and data-eid elements
        editions: list[dict] = page.evaluate("""
            () => {
                const seen = new Set();
                const result = [];

                document.querySelectorAll('a[href*="eid="]').forEach(a => {
                    try {
                        const url = new URL(a.href, location.origin);
                        const eid = url.searchParams.get('eid');
                        if (eid && !seen.has(eid)) {
                            seen.add(eid);
                            const name = (
                                a.textContent ||
                                a.getAttribute('title') ||
                                a.getAttribute('data-edition') ||
                                ''
                            ).trim().replace(/\s+/g, ' ');
                            if (name) result.push({ name, eid });
                        }
                    } catch(_) {}
                });

                document.querySelectorAll('[data-eid]').forEach(el => {
                    const eid = el.getAttribute('data-eid');
                    if (eid && !seen.has(eid)) {
                        seen.add(eid);
                        const name = (
                            el.textContent ||
                            el.getAttribute('data-name') ||
                            ''
                        ).trim().replace(/\s+/g, ' ');
                        if (name) result.push({ name, eid });
                    }
                });

                return result;
            }
        """)

        browser.close()

    log.info(f"[DT-DISCOVER] Found {len(editions)} editions")
    return sorted(editions, key=lambda x: x.get("name", ""))


def _scrape_edition_by_name_sync(
    edition_name: str, edate: str, email: str, password: str, base_url: str
) -> dict:
    """
    Login to Daily Thanthi, open the edition selector, find the district by name,
    extract its EID from the link href, navigate to ArticleView for that EID,
    and scrape articles.

    Returns {"articles": list[dict], "edate": str, "eid": str}.
    """
    import logging
    from playwright.sync_api import sync_playwright

    log = logging.getLogger(__name__)
    result: dict = {"articles": [], "pages": [], "edate": edate, "eid": ""}
    login_url = base_url.rstrip("/") + "/Login/Landingpage"
    api_base_holder: dict = {"url": ""}
    pgid_set_name: set[str] = set()
    pgid_capture_name: dict = {"active": False}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        def _capture_api(req) -> None:
            try:
                url_str = req.url
                if "getstorydetail" in url_str.lower() and not api_base_holder["url"]:
                    parsed = urlparse(url_str)
                    api_base_holder["url"] = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if pgid_capture_name["active"]:
                    m = re.search(r"[?&](?:pgid|pageid|page_id)=(\d+)", url_str, re.IGNORECASE)
                    if m:
                        pgid_set_name.add(m.group(1))
            except Exception:
                pass

        page.on("request", _capture_api)

        # ── Login ───────────────────────────────────────────────────────────────
        log.info(f"[DT-NAME] Loading login page: {login_url}")
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as err:
            log.warning(f"[DT-NAME] goto warning: {err}")
        page.wait_for_timeout(2000)

        submitted = _fill_visible_login_form(page, email, password, log)
        if not submitted:
            log.error("[DT-NAME] Login failed")
            browser.close()
            return result

        _dismiss_already_logged_in_dialog(page, log)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        log.info(f"[DT-NAME] Post-login URL: {page.url!r}")

        # ── Click the edition selector to open the edition modal ────────────────
        for sel in [
            "#selectEdition", ".selectEdition", "#editionSelect",
            "[data-target*='edition' i]", "[data-toggle][data-target*='edition' i]",
            "button:has-text('Edition')", "a:has-text('Edition')",
            ".edition-btn", "#editionBtn", ".ed-select",
            ".topnav .edition", ".nav-edition",
        ]:
            try:
                el = page.query_selector(sel)
                if el:
                    el.click()
                    page.wait_for_timeout(2000)
                    log.info(f"[DT-NAME] Clicked edition selector: {sel}")
                    break
            except Exception:
                pass

        # ── Find the matching edition link by name ───────────────────────────────
        name_lower = edition_name.lower().strip()

        found_eid: str = page.evaluate(
            """([nameLower]) => {
                // Check all anchor tags with eid= in href
                const links = Array.from(document.querySelectorAll('a[href*="eid="]'));
                for (const a of links) {
                    const text = (a.textContent || '').trim().toLowerCase();
                    if (!text || text.length > 80) continue;
                    if (text.includes(nameLower) || nameLower.includes(text)) {
                        try {
                            const u = new URL(a.href, location.origin);
                            const eid = u.searchParams.get('eid');
                            if (eid) return eid;
                        } catch(_) {}
                    }
                }
                // Also check [data-eid] elements
                for (const el of document.querySelectorAll('[data-eid]')) {
                    const text = (el.textContent || '').trim().toLowerCase();
                    if (text && (text.includes(nameLower) || nameLower.includes(text))) {
                        const eid = el.getAttribute('data-eid') || '';
                        if (eid) return eid;
                    }
                }
                return '';
            }""",
            [name_lower],
        ) or ""

        # ── Fallback: scan page HTML source for eid= near the edition name ──────
        if not found_eid:
            log.info(f"[DT-NAME] EID not in DOM — scanning page source for '{edition_name}'")
            src = page.content()
            escaped = re.escape(edition_name)
            m = re.search(
                rf"{escaped}.{{0,300}}[?&]eid=(\d+)",
                src, re.IGNORECASE | re.DOTALL,
            ) or re.search(
                rf"[?&]eid=(\d+).{{0,300}}{escaped}",
                src, re.IGNORECASE | re.DOTALL,
            )
            if m:
                found_eid = m.group(1)
                log.info(f"[DT-NAME] EID from page source: {found_eid}")

        # ── Navigate to ArticleView for this EID ─────────────────────────────────
        if found_eid:
            result["eid"] = found_eid
            edate_enc   = edate.replace("/", "%2F")
            base_av_url = f"{base_url.rstrip('/')}/Home/ArticleView"
            article_url = f"{base_av_url}?eid={found_eid}&edate={edate_enc}"

            # Enable pgid capture before navigating to target edition
            pgid_capture_name["active"] = True
            log.info(f"[DT-NAME] Navigating to: {article_url}")
            try:
                page.goto(article_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as err:
                log.warning(f"[DT-NAME] Navigation warning: {err}")
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            page.wait_for_timeout(3000)

            # Scroll sidebar to trigger lazy-loaded thumbnail XHRs
            try:
                page.evaluate("""() => {
                    document.querySelectorAll('*').forEach(el => {
                        try {
                            if (el.scrollHeight > el.clientHeight + 50)
                                el.scrollTop = el.scrollHeight;
                        } catch(_) {}
                    });
                }""")
                page.wait_for_timeout(2000)
            except Exception:
                pass

            if "login" in page.url.lower() or "landingpage" in page.url.lower():
                log.error(f"[DT-NAME] Redirected to login for eid={found_eid}")
                browser.close()
                return result

            import base64 as _b64

            def _take_shot_name() -> str:
                try:
                    jpg = page.screenshot(full_page=False, type="jpeg", quality=60)
                    return _b64.b64encode(jpg).decode("ascii")
                except Exception:
                    return ""

            from urllib.parse import parse_qs as _pqs2
            cur_pgid = _pqs2(urlparse(page.url).query).get("pgid", [""])[0]

            # ── Page 1 ──────────────────────────────────────────────────────
            first_articles = _scrape_page_articles(page, log, api_base_holder)
            all_articles: list[dict] = list(first_articles)
            log.info(f"[DT-NAME] Page 1: {len(first_articles)} articles for '{edition_name}'")

            # Build pgid → label map
            pgid_to_label: dict[str, str] = {}
            try:
                all_pg_links: dict = page.evaluate("""() => {
                    const m = {};
                    document.querySelectorAll('a[href*="pgid="]').forEach(a => {
                        try {
                            const u = new URL(a.href, location.origin);
                            const p = u.searchParams.get('pgid');
                            if (p && /^\\d+$/.test(p)) {
                                const lbl = (a.textContent || '').trim().replace(/\\s+/g,' ');
                                if (lbl && lbl.length < 60) m[p] = lbl;
                            }
                        } catch(_) {}
                    });
                    return m;
                }""") or {}
                pgid_to_label.update(all_pg_links)
            except Exception:
                pass

            sidebar_info = _find_sidebar_pages(page, page.url, log)
            for sp in sidebar_info:
                if sp.get("pgid") and sp.get("label"):
                    pgid_to_label[sp["pgid"]] = sp["label"]

            pg1_label = pgid_to_label.get(cur_pgid, "news 1")
            result["pages"].append({
                "pgid": cur_pgid,
                "label": pg1_label,
                "articles": first_articles,
                "screenshot_b64": _take_shot_name(),
            })

            # ── Pages 2..N ──────────────────────────────────────────────────
            seen_pgids: set[str] = {cur_pgid} if cur_pgid else set()
            seen_heads: set[str] = {a.get("headline", "") for a in all_articles}

            remaining_pgids: list[str] = sorted(pgid_set_name - seen_pgids)
            log.info(f"[DT-NAME] Network-captured pgids: {remaining_pgids}")

            if not remaining_pgids:
                remaining_pgids = [
                    sp.get("pgid", "")
                    for sp in sidebar_info
                    if sp.get("pgid") and sp.get("pgid") not in seen_pgids
                ]
                log.info(f"[DT-NAME] DOM-fallback pgids: {remaining_pgids}")

            page_num = 2
            for pgid in remaining_pgids[:18]:
                if not pgid or pgid in seen_pgids:
                    continue
                seen_pgids.add(pgid)
                pg_label = pgid_to_label.get(pgid, f"news {page_num}")
                pg_url   = f"{base_av_url}?eid={found_eid}&edate={edate_enc}&pgid={pgid}"
                log.info(f"[DT-NAME] Navigating to pgid={pgid} ({pg_label!r})")
                try:
                    page.goto(pg_url, wait_until="domcontentloaded", timeout=20000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    page.wait_for_timeout(2000)

                    pg_arts  = _scrape_page_articles(page, log, api_base_holder)
                    new_arts: list[dict] = []
                    for art in pg_arts:
                        h = art.get("headline", "")
                        if h not in seen_heads:
                            all_articles.append(art)
                            new_arts.append(art)
                            if h:
                                seen_heads.add(h)

                    result["pages"].append({
                        "pgid": pgid,
                        "label": pg_label,
                        "articles": new_arts,
                        "screenshot_b64": _take_shot_name(),
                    })
                    log.info(f"[DT-NAME] pgid={pgid}: {len(pg_arts)} scraped, {len(new_arts)} new")
                except Exception as ex:
                    log.warning(f"[DT-NAME] pgid={pgid} error: {ex}")
                page_num += 1

            result["articles"] = all_articles
            log.info(
                f"[DT-NAME] Done — {len(all_articles)} articles  "
                f"{len(result['pages'])} pages  eid={found_eid}  edition='{edition_name}'"
            )
        else:
            log.error(f"[DT-NAME] Could not find EID for edition '{edition_name}'")

        browser.close()

    return result


@router.post("/discover-editions")
async def discover_editions():
    """
    Login to Daily Thanthi e-paper and return all available editions with their EIDs.
    Returns {"editions": [{"name": str, "eid": str}]}.
    This is slow (requires a full Playwright login); cache the result in the frontend.
    """
    settings = get_settings()
    try:
        editions = await asyncio.to_thread(
            _discover_editions_sync,
            settings.epaper_email,
            settings.epaper_password,
            settings.epaper_base_url,
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex)[:300])
    return {"editions": editions}


@router.post("/edition-articles")
async def scrape_edition_articles(body: EditionArticlesRequest):
    """
    Scrape articles for a specific Daily Thanthi edition.
    - eid: numeric edition ID (e.g. "77"); if empty, edition_name is used for
      name-based navigation (logs in, clicks edition selector, finds by name).
    - edition_name: human-readable district name used for name-based navigation
      when eid is not a known numeric value.
    - date: DD/MM/YYYY (defaults to today)
    Returns {"eid", "edition_name", "date", "articles": [...]}.
    """
    settings = get_settings()
    eid      = body.eid.strip()
    date_str = body.date.strip() or _date.today().strftime("%d/%m/%Y")
    ed_name  = body.edition_name.strip()

    is_numeric = bool(eid and re.match(r"^\d+$", eid))

    if not is_numeric and not ed_name:
        raise HTTPException(status_code=400, detail="eid or edition_name is required")

    try:
        if is_numeric:
            result = await asyncio.to_thread(
                _scrape_edition_articles_sync,
                eid, date_str,
                settings.epaper_email,
                settings.epaper_password,
                settings.epaper_base_url,
            )
        else:
            result = await asyncio.to_thread(
                _scrape_edition_by_name_sync,
                ed_name, date_str,
                settings.epaper_email,
                settings.epaper_password,
                settings.epaper_base_url,
            )
            # Use EID discovered during name-based scraping
            if result.get("eid"):
                eid = result["eid"]
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Scrape error: {str(ex)[:300]}")

    def _clean_art(art: dict) -> dict:
        out = dict(art)
        for field in ("headline", "byline", "body"):
            if out.get(field):
                out[field] = out[field].replace("\u2013", "").replace("\u2014", "")
        return out

    # Strip en-dash/em-dash markers from ALL article text
    clean_articles = [_clean_art(a) for a in result.get("articles", [])]
    clean_pages = [
        {
            "pgid":           pg.get("pgid", ""),
            "label":          pg.get("label", ""),
            "articles":       [_clean_art(a) for a in pg.get("articles", [])],
            "screenshot_b64": pg.get("screenshot_b64", ""),
        }
        for pg in result.get("pages", [])
    ]

    return {
        "eid":          eid,
        "edition_name": ed_name,
        "date":         date_str,
        "articles":     clean_articles,
        "pages":        clean_pages,
    }


# ── Edition → PDF endpoint ────────────────────────────────────────────────────

class EditionPdfRequest(BaseModel):
    eid: str
    edition_name: str = ""
    date: str = ""  # DD/MM/YYYY; defaults to today


@router.post("/edition-pdf")
async def scrape_edition_pdf(body: EditionPdfRequest):
    """
    Scrape ALL pages for a specific Daily Thanthi edition and return a
    downloadable PDF.  Same logic as /edition-articles but returns binary PDF.
    """
    settings  = get_settings()
    eid       = body.eid.strip()
    date_str  = body.date.strip() or _date.today().strftime("%d/%m/%Y")
    ed_name   = body.edition_name.strip()

    is_numeric = bool(eid and re.match(r"^\d+$", eid))
    if not is_numeric and not ed_name:
        raise HTTPException(status_code=400, detail="eid or edition_name is required")

    try:
        if is_numeric:
            result = await asyncio.to_thread(
                _scrape_edition_articles_sync,
                eid, date_str,
                settings.epaper_email,
                settings.epaper_password,
                settings.epaper_base_url,
            )
        else:
            result = await asyncio.to_thread(
                _scrape_edition_by_name_sync,
                ed_name, date_str,
                settings.epaper_email,
                settings.epaper_password,
                settings.epaper_base_url,
            )
            if result.get("eid"):
                eid = result["eid"]
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Scrape error: {str(ex)[:300]}")

    articles = result.get("articles", [])
    for art in articles:
        for field in ("headline", "byline", "body"):
            if art.get(field):
                art[field] = art[field].replace("\u2013", "").replace("\u2014", "")

    # Build screenshots list from pages (JPEG base64 → bytes)
    import base64 as _b64pdf
    screenshots: list[dict] = []
    for pg in result.get("pages", []):
        b64 = pg.get("screenshot_b64", "")
        if b64:
            try:
                screenshots.append({"label": pg.get("label", ""), "png": _b64pdf.b64decode(b64)})
            except Exception:
                pass

    page_url = (
        f"{settings.epaper_base_url.rstrip('/')}/Home/ArticleView"
        f"?eid={eid}&edate={date_str}"
    )
    try:
        pdf_bytes = _build_pdf_from_articles(articles, page_url, date_str, screenshots or None)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(ex)[:200]}")

    edate_safe = date_str.replace("/", "-")
    fname_ed   = (ed_name or f"eid{eid}").replace(" ", "_").replace("/", "-")
    filename   = f"dailythanthi_{edate_safe}_{fname_ed}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── JSON scrape endpoint ───────────────────────────────────────────────────────

@router.post("/webpage-json")
async def scrape_webpage_json(body: WebpagePdfRequest):
    """
    Scrape and return structured JSON.
    Daily Thanthi ArticleView → article list.
    Any other URL → title + content blocks + links.
    """
    from urllib.parse import parse_qs as _pqs

    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    if _is_dailythanthi_homepage(url):
        settings = get_settings()
        try:
            result = await asyncio.to_thread(
                _scrape_epaper_today_sync,
                settings.epaper_email, settings.epaper_password, settings.epaper_base_url,
            )
        except Exception as ex:
            raise HTTPException(status_code=500, detail=str(ex)[:300])
        return result

    if _is_dailythanthi_article(url):
        settings = get_settings()
        qs    = _pqs(urlparse(url).query)
        edate = qs.get("edate", [""])[0]
        try:
            scrape_result = await asyncio.to_thread(
                _scrape_dailythanthi_sync,
                url, settings.epaper_email, settings.epaper_password, settings.epaper_base_url,
            )
        except Exception as ex:
            raise HTTPException(status_code=500, detail=str(ex)[:300])
        return {"url": url, "date": edate, "articles": scrape_result.get("articles", [])}

    try:
        data = await asyncio.to_thread(_scrape_any_url_sync, url)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex)[:200])
    return data
