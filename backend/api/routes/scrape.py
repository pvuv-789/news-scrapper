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
import json
import pdfplumber
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
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


async def _save_article(
    title: str,
    summary: str,
    url: str,
    word_count: int,
    edition_id: uuid.UUID | None,
    page_number: int,
    pub_date: _date | None = None,
) -> None:
    """
    Save an article to the DB.
    published_at is stored as the START of the given pub_date in IST (converted to UTC),
    so date-based filtering works correctly regardless of server timezone.
    If pub_date is not supplied, today's IST date is used.
    """
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    today_ist = pub_date or datetime.now(ist).date()
    # midnight IST as UTC — safe anchor for IST-date comparison in the repository
    published_at_utc = datetime(
        today_ist.year, today_ist.month, today_ist.day,
        tzinfo=ist
    ).astimezone(timezone.utc)

    async with AsyncSessionFactory() as session:
        article = Article(
            publication_id=PUBLICATION_ID,
            edition_id=edition_id,
            title=title,
            summary=summary,
            url=url,
            word_count_estimate=word_count,
            page_number=page_number,
            published_at=published_at_utc,
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


# ── Article Content (SSE streaming) route ─────────────────────────────────────

def _sse(event_type: str, **payload) -> str:
    """Format a Server-Sent Event line."""
    return f"data: {json.dumps({'type': event_type, **payload}, ensure_ascii=False)}\n\n"


@router.get("/article-content-stream")
async def scrape_article_content_stream(url: str):
    """
    Stream article extraction progress via SSE (GET).
    Events: step(message) → done(title, content, image_url, date)
    Uses Playwright + epaper login to bypass the paywall.
    """
    from playwright.async_api import async_playwright

    url = url.strip()
    today = _date.today().strftime("%d %B %Y")

    async def generate():
        if not url:
            yield _sse("done", title="", content="", image_url=None, date=today)
            return

        # ── PDF: no login needed ───────────────────────────────────────────────
        if _is_pdf_url(url):
            yield _sse("step", message="Downloading PDF…")
            try:
                async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as client:
                    resp = await client.get(url)
                if resp.status_code == 200:
                    yield _sse("step", message="Extracting PDF text…")
                    title, content, _ = _extract_pdf_text(resp.content)
                    yield _sse("done", title=title, content=content, image_url=None, date=today)
                    return
            except Exception:
                pass
            yield _sse("done", title="", content="", image_url=None, date=today)
            return

        # ── Epaper: Playwright + login ─────────────────────────────────────────
        settings = get_settings()
        title = ""
        content = ""
        image_url = None

        try:
            yield _sse("step", message="Starting browser…")
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                context = await browser.new_context(locale="ta-IN")
                page = await context.new_page()

                yield _sse("step", message="Logging in to Daily Thanthi epaper…")
                await _do_login(page, settings)

                yield _sse("step", message="Navigating to article page…")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

                yield _sse("step", message="Extracting article content…")

                # Use JS click to avoid pointer-event interception timeout
                rects = await page.query_selector_all(".pagerectangle[storyid]")
                if rects:
                    await page.evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles:true}))", rects[0])
                    await page.wait_for_timeout(2000)

                # Headline
                for sel in ["#divheadline", ".article-title", "h1"]:
                    el = await page.query_selector(sel)
                    if el:
                        t = (await el.inner_text()).strip()
                        if t:
                            title = t
                            break

                # Body
                for sel in ["#body", ".article-body", "#articleContent", "article", "main"]:
                    el = await page.query_selector(sel)
                    if el:
                        c = (await el.inner_text()).strip()
                        if c:
                            content = c
                            break

                yield _sse("step", message="Extracting image…")

                # First meaningful image
                imgs = await page.query_selector_all("img[src]")
                for img in imgs:
                    src = (await img.get_attribute("src") or "").strip()
                    if not src or src.endswith(".gif"):
                        continue
                    if any(kw in src.lower() for kw in ("logo", "icon", "sprite", "banner", "ad", "pixel")):
                        continue
                    image_url = src if src.startswith("http") else urljoin(url, src)
                    break

                await browser.close()

        except Exception as exc:
            yield _sse("step", message=f"Warning: {str(exc)[:120]}")

        yield _sse("done", title=title, content=content, image_url=image_url, date=today)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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


_TENDER_RE = re.compile(
    r"tender|டெண்டர்|classified|வரிவிளம்பர|விளம்பரங்கள்|classifieds|tenders",
    re.IGNORECASE,
)

# Broader pattern for classified/vari pages — includes தகவல்,வரி page labels
_CLASSIFIEDS_RE = re.compile(
    r"வரி\s*விளம்பரங்கள்|வரிவிளம்பர|வரி\s*விவரங்கள்"
    r"|தகவல்[,\s]*வரி|வரி[,\s]*தகவல்"
    r"|classified|classifieds|tender|டெண்டர்|விளம்பரங்கள்",
    re.IGNORECASE,
)


def _ai_summarise_tenders(text: str) -> str:
    """
    Use the Anthropic Claude API to extract and structure tender/classified
    information from raw Tamil newspaper text.
    Returns a formatted plain-text summary, or "" if the API is unavailable.
    """
    try:
        import anthropic
        _s = get_settings()
        client = anthropic.Anthropic(api_key=_s.anthropic_api_key or None)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": (
                    "The following is raw text extracted from a Tamil newspaper's "
                    "Tender / Classified section. Please extract and list each tender "
                    "or classified notice in a clean, structured format with these fields "
                    "(use English labels, Tamil values where present):\n"
                    "• Tender/Notice No.\n• Department / Authority\n"
                    "• Description\n• Last Date\n• Contact / Address\n\n"
                    "If a field is not found, write N/A. Separate each entry with a blank line.\n\n"
                    f"TEXT:\n{text[:6000]}"
                ),
            }],
        )
        return msg.content[0].text.strip() if msg.content else ""
    except Exception:
        return ""


def _build_pdf_from_articles(
    articles: list[dict],
    page_url: str,
    edate: str,
    screenshots: list[dict] | None = None,
    pages: list[dict] | None = None,
) -> bytes:
    """
    Build a complete PDF from extracted article data.
    • screenshots: list of {"label": str, "png": bytes} — page images before articles.
    • pages: full page list from scraper — used to add tender/classified sections.
    • Uses a Tamil-capable TTF font (Nirmala/Latha on Windows).
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

                # ── Embed article image (if available) ────────────────────────
                for img_src in (article.get("image_urls") or []):
                    try:
                        img_bytes: bytes | None = None
                        if img_src.startswith("data:"):
                            # base64 data-URI → decode to bytes
                            _b64part = img_src.split(",", 1)[1] if "," in img_src else ""
                            if _b64part:
                                import base64 as _b64mod
                                img_bytes = _b64mod.b64decode(_b64part)
                        elif img_src.startswith("http"):
                            # Plain URL → fetch (best-effort, no auth)
                            _r = httpx.get(
                                img_src,
                                headers=HEADERS,
                                follow_redirects=True,
                                timeout=10,
                            )
                            if _r.status_code == 200 and _r.headers.get(
                                "content-type", ""
                            ).startswith("image/"):
                                img_bytes = _r.content

                        if img_bytes:
                            _img_w = min(pw * 0.55, 90)  # max 90 mm wide
                            pdf.set_x(pdf.l_margin)
                            pdf.image(io.BytesIO(img_bytes), x=pdf.l_margin, w=_img_w)
                            pdf.ln(4)
                    except Exception:
                        pass
                    break  # one image per article is sufficient

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

    # ── Tender / Classified pages section ─────────────────────────────────────
    if pages:
        tender_pages = [pg for pg in pages if _TENDER_RE.search(pg.get("label", ""))]
        if tender_pages:
            pdf.add_page()
            _sf(18, bold=True)
            pdf.set_text_color(20, 80, 20)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pw, 12, "Tenders & Classifieds / டெண்டர் & விளம்பரங்கள்", align="C")
            pdf.ln(4)
            pdf.set_draw_color(20, 80, 20)
            pdf.set_line_width(0.6)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pw, pdf.get_y())
            pdf.set_line_width(0.2)
            pdf.ln(6)

            for pg in tender_pages:
                pg_label = pg.get("label", "")

                # ── Section label ──────────────────────────────────────────────
                _sf(13, bold=True)
                pdf.set_text_color(20, 80, 20)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(pw, 8, _rt(pg_label))
                pdf.ln(2)

                # ── Full-page image from CDN (no auth required) ────────────────
                highres = pg.get("highres_url", "")
                if highres:
                    try:
                        _hr = httpx.get(highres, headers=HEADERS,
                                        follow_redirects=True, timeout=20)
                        if _hr.status_code == 200:
                            pdf.set_x(pdf.l_margin)
                            pdf.image(io.BytesIO(_hr.content), x=pdf.l_margin, w=pw)
                            pdf.ln(4)
                    except Exception:
                        pass
                elif pg.get("screenshot_b64"):
                    try:
                        import base64 as _b64t
                        _png = _b64t.b64decode(pg["screenshot_b64"])
                        pdf.set_x(pdf.l_margin)
                        pdf.image(io.BytesIO(_png), x=pdf.l_margin, w=pw)
                        pdf.ln(4)
                    except Exception:
                        pass

                # ── Article text from tender page ──────────────────────────────
                pg_arts = pg.get("articles", [])
                raw_tender_text = ""
                for art in pg_arts:
                    if art.get("headline"):
                        _sf(11, bold=True)
                        pdf.set_text_color(20, 40, 20)
                        pdf.set_x(pdf.l_margin)
                        pdf.multi_cell(pw, 7, _rt(art["headline"]))
                        pdf.ln(1)
                        raw_tender_text += art["headline"] + "\n"
                    if art.get("body"):
                        _sf(10)
                        pdf.set_text_color(40, 40, 40)
                        pdf.set_x(pdf.l_margin)
                        pdf.multi_cell(pw, 6, _rt(art["body"]))
                        pdf.ln(3)
                        raw_tender_text += art["body"] + "\n\n"

                # ── AI-structured tender summary (RAG) ─────────────────────────
                if raw_tender_text.strip():
                    ai_summary = _ai_summarise_tenders(raw_tender_text)
                    if ai_summary:
                        pdf.ln(2)
                        _sf(11, bold=True)
                        pdf.set_text_color(0, 60, 120)
                        pdf.set_x(pdf.l_margin)
                        pdf.multi_cell(pw, 7, "AI Extracted Tender Details:", align="L")
                        pdf.ln(1)
                        pdf.set_draw_color(0, 100, 200)
                        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pw, pdf.get_y())
                        pdf.ln(3)
                        _sf(10)
                        pdf.set_text_color(30, 30, 80)
                        pdf.set_x(pdf.l_margin)
                        pdf.multi_cell(pw, 6, _safe_text(ai_summary))
                        pdf.ln(4)

                pdf.ln(4)
                pdf.set_draw_color(180, 220, 180)
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pw, pdf.get_y())
                pdf.ln(6)

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

    # Save to database — derive pub_date from edate so IST date is stored correctly
    if articles_data:
        pub_date_parsed: _date | None = None
        if edate:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    pub_date_parsed = datetime.strptime(edate, fmt).date()
                    break
                except ValueError:
                    pass

        edition_id_for_save = await _get_edition_id()
        for i, art in enumerate(articles_data, 1):
            article_url = f"{url}&storyid={art.get('story_id', i)}"
            if not await _url_exists(article_url):
                title   = art.get("headline") or "Untitled"
                summary = (art.get("body") or "")[:500]
                wc      = len((art.get("body") or "").split())
                await _save_article(
                    title, summary, article_url, wc,
                    edition_id_for_save, i, pub_date=pub_date_parsed
                )

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
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
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
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
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

    # Derive the domain for making relative image URLs absolute
    try:
        _api_parsed = urlparse(api_url)
        _api_domain = f"{_api_parsed.scheme}://{_api_parsed.netloc}"
    except Exception:
        _api_domain = ""

    for story in data.get("StoryContent", []):
        headlines: list[str] = [h.strip() for h in story.get("Headlines", []) if h and h.strip()]
        body_html: str = story.get("Body", "") or ""

        # Parse body HTML — extract image URLs before stripping tags
        soup = BeautifulSoup(body_html, "html.parser")
        image_urls: list[str] = []
        for img_tag in soup.find_all("img"):
            src = img_tag.get("src") or img_tag.get("data-src") or img_tag.get("data-lazy-src") or ""
            src = src.strip()
            if src and src not in image_urls:
                # Make relative URLs absolute
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/") and _api_domain:
                    src = _api_domain + src
                image_urls.append(src)

        # Also check dedicated photo fields in the story JSON (SAM epaper platform)
        _PHOTO_FIELDS = (
            "Photo", "photo", "PhotoUrl", "photoUrl", "photo_url",
            "PhotoPath", "photoPath", "photo_path",
            "PhotoUri", "photoUri",
            "ImageUrl", "imageUrl", "image_url",
            "ImgUrl", "imgUrl", "imgurl",
            "StoryPhoto", "storyPhoto",
            "ArticlePhoto", "articlePhoto",
            "MediaUrl", "mediaUrl", "media_url",
            "ThumbImg", "thumbImg", "ThumbnailUrl", "thumbnailUrl",
            "Photopath", "photopath",
        )
        for _field in _PHOTO_FIELDS:
            _val = (story.get(_field) or data.get(_field) or "").strip()
            if _val and _val not in image_urls:
                if _val.startswith("//"):
                    _val = "https:" + _val
                elif _val.startswith("/") and _api_domain:
                    _val = _api_domain + _val
                if _val.startswith("http") or _val.startswith("data:"):
                    image_urls.append(_val)

        # Strip HTML tags → clean plain text (Tamil chars preserved)
        body_text = soup.get_text(separator="\n", strip=True)
        body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip()

        headline = headlines[0] if headlines else ""
        sub_heads = " | ".join(headlines[1:]) if len(headlines) > 1 else ""

        if headline or body_text:
            output.append({
                "headline":   headline,
                "byline":     sub_heads,
                "dateline":   edition,
                "body":       body_text,
                "story_id":   story_id,
                "image_urls": image_urls,
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
        log.warning("[DT] No [storyid] rects — trying plain-text fallback for tender/classified page")
        # ── Plain-text fallback (tender / classified / advertisement pages) ──────
        # These pages have no story rectangles; extract all visible text blocks instead.
        try:
            raw_blocks: list[str] = page.evaluate("""
                () => {
                    const SKIP_TAGS = new Set(['SCRIPT','STYLE','NOSCRIPT','NAV','FOOTER','HEADER','ASIDE']);
                    const seen = new Set();
                    const out  = [];
                    const walk = (el) => {
                        if (SKIP_TAGS.has(el.tagName)) return;
                        if (el.childElementCount === 0) {
                            const t = (el.innerText || el.textContent || '').trim();
                            if (t.length > 20 && !seen.has(t)) { seen.add(t); out.push(t); }
                        } else {
                            for (const c of el.children) walk(c);
                        }
                    };
                    const main = document.querySelector(
                        'main, article, #contentArea, #articleContent, .article-content, body'
                    );
                    if (main) walk(main);
                    return out;
                }
            """) or []
            if raw_blocks:
                combined = "\n\n".join(raw_blocks)
                log.info(f"[DT] plain-text fallback: {len(raw_blocks)} blocks, {len(combined)} chars")
                articles.append({
                    "story_id":   "",
                    "headline":   "",
                    "byline":     "",
                    "dateline":   "",
                    "body":       combined,
                    "image_urls": [],
                })
        except Exception as ex:
            log.debug(f"[DT] plain-text fallback error: {ex}")
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

    # ── PRIMARY: httpx direct API calls (parallel) ───────────────────────────
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed
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
            def _fetch_one(sid: str):
                api_url = f"{api_base_holder['url']}?Storyid={sid}"
                try:
                    resp = client.get(api_url)
                    log.info(f"[DT] httpx {sid}: status={resp.status_code}")
                    return sid, resp
                except Exception as ex:
                    log.warning(f"[DT] httpx error {sid}: {ex}")
                    return sid, None

            results_map: dict = {}
            with ThreadPoolExecutor(max_workers=8) as _exe:
                futs = {_exe.submit(_fetch_one, sid): sid for sid in story_ids}
                for fut in _as_completed(futs):
                    try:
                        sid, resp = fut.result()
                        results_map[sid] = resp
                    except Exception:
                        pass

            for sid in story_ids:
                resp = results_map.get(sid)
                if resp is not None and resp.status_code == 200:
                    api_url = f"{api_base_holder['url']}?Storyid={sid}"
                    before = len(articles)
                    _parse_story_response(resp.json(), api_url, articles)
                    log.info(f"[DT] httpx parsed {sid}: +{len(articles) - before}")
    except Exception as ex:
        log.error(f"[DT] httpx session error: {ex}")

    log.info(f"[DT] httpx extracted {len(articles)} articles from {len(story_ids)} stories")

    if articles:
        # Supplement any missing article images via a quick DOM click pass
        _supplement_article_images(page, log, articles, rects)
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

            # Snapshot before click so we can detect newly loaded images
            before_imgs = _snapshot_visible_imgs(page)

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

            # Capture article photo: compare before/after to isolate new image
            img_urls = _best_img_urls_from_page(page, log, before_imgs)

            log.info(f"[DT] DOM sid={sid} head={headline[:60]!r} body_len={len(body)} imgs={len(img_urls)}")

            if headline or body:
                dom_articles.append({
                    "story_id":   sid,
                    "headline":   headline,
                    "byline":     byline,
                    "dateline":   dateline,
                    "body":       body,
                    "image_urls": img_urls,
                })
        except Exception as ex:
            log.debug(f"[DT] DOM click error sid={sid}: {ex}")

    log.info(f"[DT] DOM fallback extracted {len(dom_articles)} articles")
    return dom_articles


def _snapshot_visible_imgs(page) -> set[str]:
    """Return the set of src URLs for all currently visible images on the page."""
    try:
        return set(page.evaluate("""
            () => Array.from(document.querySelectorAll('img[src]'))
                       .map(i => i.src)
                       .filter(Boolean)
        """) or [])
    except Exception:
        return set()


def _is_page_scan_url(url: str) -> bool:
    """
    Return True ONLY for obvious layout/chrome images that are never article photos.
    CloudFront article-crop images (e.g. HASH_01_hr.jpg) are NOT filtered here —
    they are fetched with session cookies in _fetch_img_as_b64.
    """
    _SCAN_RE = re.compile(
        r"/pageimages?/"
        r"|/thumbimg"
        r"|/pagescan/"
        r"|[?&](thumb|thumbnail)=",
        re.IGNORECASE,
    )
    return bool(_SCAN_RE.search(url))


def _fetch_img_as_b64(url: str, cookies: dict) -> str:
    """
    Fetch an image URL using the browser's session cookies so auth-gated
    images are accessible.  Returns a data-URI string, or "" on failure.
    """
    import base64
    try:
        with httpx.Client(
            cookies=cookies,
            headers={**HEADERS, "Referer": "https://epaper.dailythanthi.com/"},
            follow_redirects=True,
            timeout=12,
        ) as cl:
            r = cl.get(url)
        if r.status_code == 200:
            ct = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if ct.startswith("image/"):
                b64 = base64.b64encode(r.content).decode()
                return f"data:{ct};base64,{b64}"
    except Exception:
        pass
    return ""


def _best_img_urls_from_page(page, log, before_srcs: set[str]) -> list[str]:
    """
    Compare visible images after a story rect click against the pre-click snapshot.
    Returns the article photo as a base64 data-URI (fetched via session cookies)
    so it displays correctly in the viewer and can be embedded in PDFs.

    Excludes newspaper page-scan CDN images (_hr.jpg etc.) which are not article
    photos and return Access Denied when loaded without CloudFront signed cookies.
    """
    try:
        origin = ""
        pu = urlparse(page.url)
        origin = f"{pu.scheme}://{pu.netloc}"
    except Exception:
        pass

    _SKIP = re.compile(r"spacer|logo|icon|arrow|close|\.gif$", re.IGNORECASE)

    def _norm(src: str) -> str:
        src = (src or "").strip()
        if src.startswith("//"):
            return "https:" + src
        if src.startswith("/") and origin:
            return origin + src
        return src

    def _resolve(src: str) -> str:
        """Normalise URL, fetch with auth and return base64 data-URI."""
        src = _norm(src)
        if not src.startswith("http"):
            return ""
        try:
            cookies = {c["name"]: c["value"] for c in page.context.cookies()}
        except Exception:
            cookies = {}
        b64_uri = _fetch_img_as_b64(src, cookies)
        if b64_uri:
            log.info(f"[DT-IMG] fetched as b64 ({len(b64_uri)} chars): {src[:80]}")
            return b64_uri
        # If fetch fails, return the URL — viewer hides it via onerror
        log.info(f"[DT-IMG] returning raw URL (fetch failed): {src[:80]}")
        return src

    # -- (1) NEW images that appeared after the click (most reliable) -------------
    try:
        all_imgs = page.evaluate("""
            () => Array.from(document.querySelectorAll('img[src], img[data-src]'))
                .map(img => {
                    const r   = img.getBoundingClientRect();
                    const src = img.src || img.getAttribute('data-src') || '';
                    return { src, w: r.width, h: r.height, area: r.width * r.height };
                })
                .filter(o => o.area >= 2500 && o.w >= 50 && o.h >= 50 && o.src)
        """) or []

        new_imgs = [
            o for o in all_imgs
            if o["src"] not in before_srcs
            and not _SKIP.search(o["src"])
            and not _is_page_scan_url(o["src"])
        ]
        if new_imgs:
            new_imgs.sort(key=lambda o: o["area"], reverse=True)
            resolved = _resolve(new_imgs[0]["src"])
            if resolved:
                return [resolved]
    except Exception:
        pass

    # -- (2) Targeted selectors for common SAM-epaper article photo containers ----
    _SELS = [
        "#divphoto img", "#divPhoto img",
        "#imgPhoto", "#imgphoto", "#imgStory", "#imgstory", "#imgArticle",
        "#divStoryImage img", "#divstoryimage img", "#storyImage img",
        "#photoDiv img", "#divArticleImage img",
        ".story-image img", ".article-image img",
        ".storyPhoto img", ".articlePhoto img",
        "#divDetailedStory img", "#divStoryText img", "#divNewsText img",
    ]
    for sel in _SELS:
        try:
            el = page.query_selector(sel)
            if not el:
                continue
            box = el.bounding_box()
            if not box or box["width"] < 50 or box["height"] < 50:
                continue
            src = el.get_attribute("src") or el.get_attribute("data-src") or ""
            if not src or _SKIP.search(src) or _is_page_scan_url(src):
                continue
            resolved = _resolve(src)
            if resolved:
                log.info(f"[DT-IMG] selector {sel}: {src[:80]}")
                return [resolved]
        except Exception:
            pass

    # -- (3) Largest non-page-scan visible image as last resort -------------------
    try:
        imgs = page.evaluate("""
            () => Array.from(document.querySelectorAll('img[src]'))
                .map(img => {
                    const r = img.getBoundingClientRect();
                    return { src: img.src, area: r.width * r.height, w: r.width, h: r.height };
                })
                .filter(o => o.area >= 5000 && o.w >= 80 && o.h >= 80 && o.src)
                .sort((a, b) => b.area - a.area)
                .map(o => o.src)
        """) or []
        for candidate in imgs:
            if (
                not _SKIP.search(candidate)
                and not _is_page_scan_url(candidate)
                and candidate not in before_srcs
            ):
                resolved = _resolve(candidate)
                if resolved:
                    log.info(f"[DT-IMG] fallback largest: {candidate[:80]}")
                    return [resolved]
    except Exception:
        pass

    return []


def _supplement_article_images(page, log, articles: list[dict], rects) -> None:
    """
    After the primary httpx extraction, click each story rect to capture
    the article photo URL from the live DOM — only for articles with no images.
    Uses before/after image comparison to isolate the article photo.
    Adds URLs directly into each article dict's 'image_urls' list.
    """
    if not articles or not rects:
        return

    no_img = sum(1 for a in articles if not a.get("image_urls"))
    if no_img == 0:
        return

    sid_map: dict[str, dict] = {
        a.get("story_id", ""): a for a in articles if a.get("story_id")
    }
    log.info(f"[DT-IMG] Supplementing images for {no_img}/{len(articles)} articles")

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
            art = sid_map.get(sid)
            if not art or art.get("image_urls"):
                continue

            # Snapshot images before clicking
            before = _snapshot_visible_imgs(page)

            rect.click()
            page.wait_for_timeout(1200)

            img_urls = _best_img_urls_from_page(page, log, before)
            if img_urls:
                art["image_urls"] = img_urls
                log.info(f"[DT-IMG] sid={sid} → {img_urls[0][:80]}")
        except Exception as ex:
            log.debug(f"[DT-IMG] supplement sid={sid}: {ex}")


def _get_page_cdnurls_sync(page, log) -> dict[str, dict]:
    """
    Extract per-page CDN image URLs from the ArticleView page's
    #ddl_Pages <select> dropdown.  Each <option> carries:
      value     = pgid
      highres   = medium-res JPEG URL  (CDN, no auth required)
      xhighres  = full-res  JPEG URL   (CDN, no auth required)
      pgno      = page number string
      text      = page label (e.g. "வரிவிளம்பரங்கள் 2", "டெண்டர் 5")

    Returns dict[pgid -> {"label","highres","xhighres","pgno"}].
    """
    try:
        data: dict = page.evaluate(r"""
            () => {
                const sel = document.querySelector(
                    'select#ddl_Pages, select.selectpicker[id*="Pages"], select[id*="page" i]'
                );
                if (!sel) return {};
                const m = {};
                for (const opt of sel.options) {
                    const pgid = (opt.value || '').trim();
                    if (!pgid || !/^\d+$/.test(pgid)) continue;
                    m[pgid] = {
                        label:    (opt.textContent || '').trim(),
                        highres:  opt.getAttribute('highres')  || '',
                        xhighres: opt.getAttribute('xhighres') || '',
                        pgno:     opt.getAttribute('pgno')     || '',
                    };
                }
                return m;
            }
        """) or {}
        log.info(f"[DT-CDNURL] Extracted {len(data)} page CDN URLs from ddl_Pages")
        return data
    except Exception as ex:
        log.warning(f"[DT-CDNURL] ddl_Pages extraction failed: {ex}")
        return {}


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


def _get_all_pgids_via_api(
    page, eid: str, edate: str, log, current_pgid: str = ""
) -> list[str]:
    """
    Fetch ALL newspaper page IDs for (eid, edate) from the epaper's own API:
        GET /Home/GetAllpages?editionid={eid}&editiondate={encoded_edate}

    This is the most reliable approach because page IDs change every day and
    the API always returns the complete, up-to-date list for the current date.
    Authentication uses the browser session cookies from the already-logged-in
    Playwright page so no separate login is needed.

    Returns a deduplicated list of pgid strings (excluding current_pgid).
    Used purely for finding pgids, preserving generic labeling so the 
    frontend font/UI isn't broken.
    """
    from urllib.parse import quote as _quote
    import httpx

    try:
        from urllib.parse import urlparse
        base_origin = urlparse(page.url).scheme + "://" + urlparse(page.url).netloc
        edate_enc   = _quote(edate, safe="")
        api_url     = f"{base_origin}/Home/GetAllpages?editionid={eid}&editiondate={edate_enc}"
        log.info(f"[DT-PGIDS] Calling GetAllpages API: {api_url}")

        cookies_dict = {c["name"]: c["value"] for c in page.context.cookies()}
        hdrs = {
            "User-Agent":       page.evaluate("navigator.userAgent"),
            "Referer":          page.url,
            "X-Requested-With": "XMLHttpRequest",
            "Accept":           "application/json, text/javascript, */*; q=0.01",
        }

        with httpx.Client(cookies=cookies_dict, headers=hdrs, follow_redirects=True, timeout=20) as client:
            resp = client.get(api_url)

        if resp.status_code != 200:
            log.warning(f"[DT-PGIDS] Non-200 response: {resp.status_code}")
            return []

        data = resp.json()
        items = data if isinstance(data, list) else (
            data.get("pages") or data.get("Pages") or
            data.get("data")  or data.get("Data")  or []
        )

        pgids: list[str] = []
        seen: set[str] = set()

        for item in items:
            if isinstance(item, dict):
                pid = str(
                    item.get("PageId")   or item.get("pageId")   or
                    item.get("pgid")     or item.get("Pgid")     or
                    item.get("page_id")  or item.get("PageCode") or
                    item.get("pageid")   or ""
                ).strip()
            elif isinstance(item, (str, int)):
                pid = str(item).strip()
            else:
                continue

            if pid and pid.isdigit() and pid not in seen:
                seen.add(pid)
                if pid != current_pgid:
                    pgids.append(pid)

        log.info(f"[DT-PGIDS] Found {len(pgids)} additional page IDs from API")
        return pgids

    except Exception as ex:
        log.warning(f"[DT-PGIDS] GetAllpages API error: {ex}")
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
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
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
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
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


# ── Edition-specific daily PDF ─────────────────────────────────────────────────

def _scrape_edition_date_sync(
    edition_code: str,
    target_date: str,   # YYYY-MM-DD
    email: str,
    password: str,
    base_url: str,
) -> dict:
    """
    Login and scrape ALL articles (with images) for a given edition + date.
    Returns {"edition": {...}, "articles": [...], "screenshots": [...]}.
    Runs synchronously — call via asyncio.to_thread().
    """
    import logging
    from playwright.sync_api import sync_playwright

    log = logging.getLogger(__name__)

    all_articles: list[dict] = []
    seen_heads:   set[str]   = set()
    screenshots:  list[dict] = []
    edition_info = {
        "date": target_date,
        "edition": edition_code,
        "pages_scraped": 0,
        "total_articles": 0,
    }

    login_url        = base_url.rstrip("/") + "/Login/Landingpage"
    edition_page_url = (
        f"{base_url.rstrip('/')}/Home/GetEditionPages"
        f"?editionName={edition_code}&date={target_date}"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # ── Login ──────────────────────────────────────────────────────────────
        log.info(f"[DT-EDITION] Login page: {login_url}")
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as err:
            log.warning(f"[DT-EDITION] Login page warning: {err}")
        page.wait_for_timeout(2000)

        submitted = _fill_visible_login_form(page, email, password, log)
        if not submitted:
            log.error("[DT-EDITION] Login form not submitted")
            browser.close()
            return {"edition": edition_info, "articles": all_articles, "screenshots": screenshots}

        _dismiss_already_logged_in_dialog(page, log)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        # ── Navigate to this edition/date ──────────────────────────────────────
        log.info(f"[DT-EDITION] Edition page: {edition_page_url}")
        try:
            page.goto(edition_page_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as err:
            log.warning(f"[DT-EDITION] Edition page warning: {err}")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        # ── Capture getstorydetail API base (for image URLs) ──────────────────
        api_base_holder: dict = {"url": ""}

        def _capture_api(req) -> None:
            try:
                if "getstorydetail" in req.url.lower() and not api_base_holder["url"]:
                    parsed = urlparse(req.url)
                    api_base_holder["url"] = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            except Exception:
                pass

        page.on("request", _capture_api)

        # ── Find ArticleView links ─────────────────────────────────────────────
        article_view_urls: list[str] = page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a[href*="ArticleView"]'));
                return [...new Set(links.map(a => a.href))];
            }
        """) or []

        # Fallback: click page thumbnail images to reveal ArticleView links
        if not article_view_urls:
            log.info("[DT-EDITION] No ArticleView links found directly — clicking thumbnails")
            thumbs = page.query_selector_all(
                ".pageimg, .page-thumbnail, [data-pageid], img[class*='page'], .pageItem img"
            )
            for thumb in thumbs[:10]:
                try:
                    thumb.click()
                    page.wait_for_timeout(1500)
                    new_urls = page.evaluate("""
                        () => {
                            const links = Array.from(document.querySelectorAll('a[href*="ArticleView"]'));
                            return [...new Set(links.map(a => a.href))];
                        }
                    """) or []
                    article_view_urls.extend(new_urls)
                except Exception:
                    pass
            article_view_urls = list(dict.fromkeys(article_view_urls))

        article_view_urls = article_view_urls[:8]   # cap to avoid very long runs
        log.info(f"[DT-EDITION] ArticleView URLs: {len(article_view_urls)}")

        # ── Scrape current page directly if no ArticleView links ───────────────
        if not article_view_urls:
            log.info("[DT-EDITION] Scraping current page directly")
            try:
                png = page.screenshot(full_page=False)
                screenshots.append({"label": f"{edition_code} – {target_date}", "png": png})
            except Exception:
                pass
            page_arts = _scrape_page_articles(page, log, api_base_holder)
            for art in page_arts:
                h = art.get("headline", "")
                if h not in seen_heads:
                    all_articles.append(art)
                    if h:
                        seen_heads.add(h)
        else:
            for av_url in article_view_urls:
                log.info(f"[DT-EDITION] Scraping: {av_url}")
                try:
                    page.goto(av_url, wait_until="domcontentloaded", timeout=30000)
                except Exception as err:
                    log.warning(f"[DT-EDITION] Nav warning: {err}")
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)

                try:
                    png = page.screenshot(full_page=False)
                    screenshots.append({"label": f"{edition_code} – page {edition_info['pages_scraped'] + 1}", "png": png})
                except Exception:
                    pass

                page_arts = _scrape_page_articles(page, log, api_base_holder)
                for art in page_arts:
                    h = art.get("headline", "")
                    if h not in seen_heads:
                        all_articles.append(art)
                        if h:
                            seen_heads.add(h)

                edition_info["pages_scraped"] += 1

        browser.close()

    edition_info["total_articles"] = len(all_articles)
    log.info(f"[DT-EDITION] Done — {len(all_articles)} articles, {len(screenshots)} screenshots")
    return {"edition": edition_info, "articles": all_articles, "screenshots": screenshots}


@router.get("/edition-daily-pdf")
async def download_edition_daily_pdf(edition: str, date: str = ""):
    """
    Scrape today's (or given date's) news for the specified edition and return a PDF.
    edition: city_code from the editions table  (e.g. "ChennaiCity", "Coimbatore")
    date:    YYYY-MM-DD  (defaults to today)
    """
    edition_code = edition.strip()
    if not edition_code:
        raise HTTPException(status_code=400, detail="edition is required")

    target_date = date.strip() if date.strip() else _date.today().strftime("%Y-%m-%d")
    settings    = get_settings()

    try:
        result = await asyncio.to_thread(
            _scrape_edition_date_sync,
            edition_code,
            target_date,
            settings.epaper_email,
            settings.epaper_password,
            settings.epaper_base_url,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scrape error: {str(e)[:300]}")

    articles_data = result.get("articles", [])
    screenshots   = result.get("screenshots", [])
    edate         = result["edition"].get("date", target_date)

    source_url = f"{settings.epaper_base_url} — {edition_code} — {target_date}"
    try:
        pdf_bytes = _build_pdf_from_articles(articles_data, source_url, edate, screenshots)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF build failed: {str(e)[:200]}")

    filename = f"dailythanthi_{edition_code}_{target_date}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
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


def _api_scrape_all_pages(
    cookies: dict,
    base_origin: str,
    eid: str,
    edate: str,          # DD/MM/YYYY
    cur_pgid: str,
    cdn_url_map: dict,   # pgid → {"label","highres","xhighres","pgno"}
    log,
) -> tuple[list[dict], list[dict]]:
    """
    Fast API-only scrape: replaces per-page Playwright navigation with parallel
    httpx calls.

      1. GetAllpages → all page IDs + labels + CDN URLs
      2. getingRectangleObject for every page (parallel, max 8 workers)
      3. getstorydetail for every story ID (parallel, max 10 workers)

    Returns (all_articles, pages_list) — same shape as the browser-based path.
    """
    from urllib.parse import quote as _quote
    from concurrent.futures import ThreadPoolExecutor, as_completed as _asc

    edate_enc = _quote(edate, safe="")
    # httpx.Client is NOT thread-safe — each worker creates its own client
    client_kwargs = dict(
        cookies=cookies,
        headers={
            "User-Agent":       HEADERS["User-Agent"],
            "Referer":          f"{base_origin}/Home/ArticleView?eid={eid}&edate={edate_enc}",
            "X-Requested-With": "XMLHttpRequest",
            "Accept":           "application/json, text/javascript, */*; q=0.01",
        },
        follow_redirects=True,
        timeout=20,
    )
    api_story_base = f"{base_origin}/Home/getstorydetail"

    def _make_client() -> httpx.Client:
        return httpx.Client(**client_kwargs)

    # ── 1. GetAllpages → full page list (single call, own client) ─────────────
    allpages_url = (
        f"{base_origin}/Home/GetAllpages"
        f"?editionid={eid}&editiondate={edate_enc}"
    )
    log.info(f"[DT-FAST] GetAllpages: {allpages_url}")
    try:
        with _make_client() as c:
            resp = c.get(allpages_url)
        raw = resp.json() if resp.status_code == 200 else []
    except Exception as ex:
        log.warning(f"[DT-FAST] GetAllpages failed: {ex}")
        raw = []

    pages_meta: list[dict] = raw if isinstance(raw, list) else (
        raw.get("pages") or raw.get("Pages") or
        raw.get("data")  or raw.get("Data")  or []
    )
    log.info(f"[DT-FAST] {len(pages_meta)} pages from GetAllpages")

    # ── Build ordered page list (current page first) ───────────────────────────
    ordered: list[dict] = []
    seen_pids: set[str] = set()
    if cur_pgid:
        ordered.append({
            "pgid":    cur_pgid,
            "label":   cdn_url_map.get(cur_pgid, {}).get("label", "news 1"),
            "highres": (cdn_url_map.get(cur_pgid, {}).get("xhighres")
                        or cdn_url_map.get(cur_pgid, {}).get("highres", "")),
        })
        seen_pids.add(cur_pgid)

    for item in pages_meta:
        if not isinstance(item, dict):
            continue
        pid = str(
            item.get("PageId") or item.get("pageId") or
            item.get("pgid")   or item.get("Pgid")   or
            item.get("pageid") or ""
        ).strip()
        if not pid or not pid.isdigit() or pid in seen_pids:
            continue
        seen_pids.add(pid)
        label = str(
            item.get("NewsProPageTitle") or item.get("PageTitle") or
            item.get("pageTitle")        or
            cdn_url_map.get(pid, {}).get("label", "") or
            f"page {item.get('PageNo', '')}"
        ).strip()
        highres = str(
            item.get("XHighResolution") or item.get("HighResolution") or
            item.get("highResolution")  or
            cdn_url_map.get(pid, {}).get("xhighres") or
            cdn_url_map.get(pid, {}).get("highres") or ""
        ).strip()
        ordered.append({"pgid": pid, "label": label, "highres": highres})

    # Fallback: CDN map if GetAllpages returned nothing useful
    if len(ordered) <= 1:
        for pid, info in cdn_url_map.items():
            if pid and pid not in seen_pids:
                seen_pids.add(pid)
                ordered.append({
                    "pgid":    pid,
                    "label":   info.get("label", f"page-{pid}"),
                    "highres": info.get("xhighres") or info.get("highres", ""),
                })

    log.info(f"[DT-FAST] Processing {len(ordered)} pages")

    # ── 2. getingRectangleObject — each worker owns its own httpx.Client ───────
    def _fetch_rects(pg_info: dict) -> dict:
        pid = pg_info["pgid"]
        url = f"{base_origin}/Home/getingRectangleObject?pageid={pid}"
        try:
            with _make_client() as c:
                r = c.get(url, timeout=15)
            if r.status_code != 200:
                log.warning(f"[DT-FAST] Rects pgid={pid} HTTP {r.status_code}")
                return {**pg_info, "story_ids": []}
            data = r.json()
            rect_list = data if isinstance(data, list) else (
                data.get("rectangles") or data.get("Rectangles") or []
            )
            sids: list[str] = []
            seen_s: set[str] = set()
            for rect in rect_list:
                if not isinstance(rect, dict):
                    continue
                sid = str(
                    rect.get("StoryId") or rect.get("storyId") or
                    rect.get("storyid") or ""
                ).strip()
                if sid and sid != "0" and sid not in seen_s:
                    seen_s.add(sid)
                    sids.append(sid)
            log.info(f"[DT-FAST] pgid={pid}: {len(sids)} story IDs")
            return {**pg_info, "story_ids": sids}
        except Exception as ex:
            log.warning(f"[DT-FAST] Rects pgid={pid}: {ex}")
            return {**pg_info, "story_ids": []}

    pages_with_sids: list[dict | None] = [None] * len(ordered)
    with ThreadPoolExecutor(max_workers=6) as exe:
        idx_futs = {exe.submit(_fetch_rects, pg): i for i, pg in enumerate(ordered)}
        for fut in _asc(idx_futs):
            i = idx_futs[fut]
            try:
                pages_with_sids[i] = fut.result()
            except Exception:
                pages_with_sids[i] = {**ordered[i], "story_ids": []}

    total_sids = sum(len(pg.get("story_ids", [])) for pg in pages_with_sids if pg)
    log.info(f"[DT-FAST] Total story IDs: {total_sids}")

    # ── 3. getstorydetail — each worker owns its own httpx.Client ─────────────
    all_sids_ordered: list[str] = []
    seen_global: set[str] = set()
    for pg in pages_with_sids:
        if pg:
            for sid in (pg.get("story_ids") or []):
                if sid not in seen_global:
                    seen_global.add(sid)
                    all_sids_ordered.append(sid)

    def _fetch_story(sid: str):
        url = f"{api_story_base}?Storyid={sid}"
        try:
            with _make_client() as c:
                r = c.get(url, timeout=20)
            return sid, r if r.status_code == 200 else None
        except Exception as ex:
            log.warning(f"[DT-FAST] Story {sid}: {ex}")
            return sid, None

    story_results: dict = {}
    with ThreadPoolExecutor(max_workers=8) as exe:
        futs2 = {exe.submit(_fetch_story, sid): sid for sid in all_sids_ordered}
        for fut in _asc(futs2):
            try:
                sid, r = fut.result()
                if r is not None:
                    story_results[sid] = r
            except Exception:
                pass
    log.info(f"[DT-FAST] {len(story_results)}/{len(all_sids_ordered)} stories fetched")

    # ── 4. Build pages + articles ──────────────────────────────────────────────
    pages_out: list[dict] = []
    all_articles: list[dict] = []
    seen_heads: set[str] = set()

    for pg in pages_with_sids:
        if not pg:
            continue
        pg_articles: list[dict] = []
        for sid in (pg.get("story_ids") or []):
            r = story_results.get(sid)
            if r is None:
                continue
            parsed: list[dict] = []
            try:
                _parse_story_response(
                    r.json(), f"{api_story_base}?Storyid={sid}", parsed
                )
            except Exception:
                pass
            for art in parsed:
                h = art.get("headline", "")
                if h not in seen_heads:
                    seen_heads.add(h)
                    pg_articles.append(art)
                    all_articles.append(art)

        pages_out.append({
            "pgid":           pg["pgid"],
            "label":          pg["label"],
            "articles":       pg_articles,
            "screenshot_b64": "",
            "highres_url":    pg.get("highres", ""),
        })
        log.info(
            f"[DT-FAST] pgid={pg['pgid']} label={pg['label']!r}: "
            f"{len(pg_articles)} articles"
        )

    return all_articles, pages_out


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
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
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
        page.wait_for_timeout(1000)

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
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
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
                    page.wait_for_timeout(1000)
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
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
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
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        log.info(f"[DT-EDITION] Final URL for eid={eid}: {page.url!r}")

        if "login" in page.url.lower() or "landingpage" in page.url.lower():
            log.error(f"[DT-EDITION] Still on login page — aborting eid={eid}")
            browser.close()
            return result

        # ── Step 5: Scrape page 1 ─────────────────────────────────────────────
        import base64 as _b64

        def _take_shot() -> str:
            try:
                page.wait_for_timeout(1500)
                jpg = page.screenshot(full_page=False, type="jpeg", quality=65)
                return _b64.b64encode(jpg).decode("ascii")
            except Exception:
                return ""

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

        sidebar_info = _find_sidebar_pages(page, page.url, log)
        for sp in sidebar_info:
            if sp.get("pgid") and sp.get("label"):
                pgid_to_label[sp["pgid"]] = sp["label"]

        cdn_url_map: dict[str, dict] = _get_page_cdnurls_sync(page, log)
        for pgid_cdn, info_cdn in cdn_url_map.items():
            if info_cdn.get("label") and pgid_cdn not in pgid_to_label:
                pgid_to_label[pgid_cdn] = info_cdn["label"]

        pg1_label = pgid_to_label.get(cur_pgid, "") or cdn_url_map.get(cur_pgid, {}).get("label", "news 1")
        log.info(f"[DT-EDITION] Page 1 label={pg1_label!r} pgid={cur_pgid}")

        pg1_cdn = cdn_url_map.get(cur_pgid, {})
        pg1_shot = "" if (pg1_cdn.get("xhighres") or pg1_cdn.get("highres")) else _take_shot()

        first_articles = _scrape_page_articles(page, log, api_base_holder)
        all_articles: list[dict] = list(first_articles)
        log.info(f"[DT-EDITION] Page 1: {len(first_articles)} articles")

        result["pages"].append({
            "pgid":           cur_pgid,
            "label":          pg1_label,
            "articles":       first_articles,
            "screenshot_b64": pg1_shot,
            "highres_url":    pg1_cdn.get("xhighres") or pg1_cdn.get("highres") or "",
        })

        # ── Step 6: Traverse remaining pages ─────────────────────────────────
        seen_pgids: set[str] = {cur_pgid} if cur_pgid else set()
        seen_heads: set[str] = {a.get("headline", "") for a in all_articles}

        remaining_pgids: list[str] = _get_all_pgids_via_api(page, eid, edate, log, cur_pgid)
        log.info(f"[DT-EDITION] GetAllpages API pgids: {remaining_pgids}")

        if not remaining_pgids:
            remaining_pgids = sorted(pgid_set - seen_pgids)
            log.info(f"[DT-EDITION] Network-captured extra pgids: {remaining_pgids}")

        if not remaining_pgids:
            remaining_pgids = [
                sp.get("pgid", "")
                for sp in sidebar_info
                if sp.get("pgid") and sp.get("pgid") not in seen_pgids
            ]
            log.info(f"[DT-EDITION] DOM-fallback pgids: {remaining_pgids}")

        if not remaining_pgids:
            remaining_pgids = [p for p in cdn_url_map if p and p not in seen_pgids]
            log.info(f"[DT-EDITION] CDN-map fallback pgids: {remaining_pgids}")

        base_av_url = f"{base_url.rstrip('/')}/Home/ArticleView"
        edate_enc   = edate.replace("/", "%2F")
        page_num    = 2

        for pgid in remaining_pgids[:60]:
            if not pgid or pgid in seen_pgids:
                continue
            seen_pgids.add(pgid)

            pg_cdn   = cdn_url_map.get(pgid, {})
            pg_label = pg_cdn.get("label") or pgid_to_label.get(pgid, f"news {page_num}")
            pg_url   = f"{base_av_url}?eid={eid}&edate={edate_enc}&pgid={pgid}"
            log.info(f"[DT-EDITION] Navigating to pgid={pgid} ({pg_label!r})")
            try:
                page.goto(pg_url, wait_until="domcontentloaded", timeout=20000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(800)

                pg_shot = "" if (pg_cdn.get("xhighres") or pg_cdn.get("highres")) else _take_shot()

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
                    "pgid":           pgid,
                    "label":          pg_label,
                    "articles":       new_arts,
                    "screenshot_b64": pg_shot,
                    "highres_url":    pg_cdn.get("xhighres") or pg_cdn.get("highres") or "",
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
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
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
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
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
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
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
                    page.wait_for_timeout(1000)
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
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(2000)

            if "login" in page.url.lower() or "landingpage" in page.url.lower():
                log.error(f"[DT-NAME] Redirected to login for eid={found_eid}")
                browser.close()
                return result

            import base64 as _b64

            def _take_shot_name() -> str:
                try:
                    page.wait_for_timeout(1500)
                    jpg = page.screenshot(full_page=False, type="jpeg", quality=65)
                    return _b64.b64encode(jpg).decode("ascii")
                except Exception:
                    return ""

            from urllib.parse import parse_qs as _pqs2
            cur_pgid = _pqs2(urlparse(page.url).query).get("pgid", [""])[0]

            # Build pgid → label map FIRST
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

            # ── Extract CDN image URLs for ALL pages from ddl_Pages dropdown ─────
            cdn_url_map_name: dict[str, dict] = _get_page_cdnurls_sync(page, log)
            # Supplement labels from CDN map (more accurate Tamil page labels)
            for pgid_cdn, info_cdn in cdn_url_map_name.items():
                if info_cdn.get("label") and pgid_cdn not in pgid_to_label:
                    pgid_to_label[pgid_cdn] = info_cdn["label"]

            pg1_label = cdn_url_map_name.get(cur_pgid, {}).get("label") or pgid_to_label.get(cur_pgid, "news 1")

            # ── Page 1: skip screenshot if CDN URL available ─────────────────
            pg1_cdn = cdn_url_map_name.get(cur_pgid, {})
            pg1_shot = "" if (pg1_cdn.get("xhighres") or pg1_cdn.get("highres")) else _take_shot_name()
            first_articles = _scrape_page_articles(page, log, api_base_holder)
            all_articles: list[dict] = list(first_articles)
            log.info(f"[DT-NAME] Page 1: {len(first_articles)} articles for '{edition_name}'")

            result["pages"].append({
                "pgid":          cur_pgid,
                "label":         pg1_label,
                "articles":      first_articles,
                "screenshot_b64": pg1_shot,
                "highres_url":   pg1_cdn.get("xhighres") or pg1_cdn.get("highres") or "",
            })

            # ── Pages 2..N ──────────────────────────────────────────────────
            seen_pgids: set[str] = {cur_pgid} if cur_pgid else set()
            seen_heads: set[str] = {a.get("headline", "") for a in all_articles}

            # Primary: call the epaper's GetAllpages API
            remaining_pgids: list[str] = _get_all_pgids_via_api(page, found_eid, edate, log, cur_pgid)
            log.info(f"[DT-NAME] GetAllpages API pgids: {remaining_pgids}")

            # Fallback 1: network-captured pgids from sidebar
            if not remaining_pgids:
                remaining_pgids = sorted(pgid_set_name - seen_pgids)
                log.info(f"[DT-NAME] Network-captured pgids: {remaining_pgids}")

            # Fallback 2: DOM sequence
            if not remaining_pgids:
                remaining_pgids = [
                    sp.get("pgid", "")
                    for sp in sidebar_info
                    if sp.get("pgid") and sp.get("pgid") not in seen_pgids
                ]
                log.info(f"[DT-NAME] DOM-fallback pgids: {remaining_pgids}")

            # Fallback 3: pgids from CDN URL map (ddl_Pages — most complete source)
            if not remaining_pgids:
                remaining_pgids = [p for p in cdn_url_map_name if p and p not in seen_pgids]
                log.info(f"[DT-NAME] CDN-map fallback pgids: {remaining_pgids}")

            page_num = 2
            for pgid in remaining_pgids[:60]:  # cap at 60 pages to cover Tenders/Classifieds
                if not pgid or pgid in seen_pgids:
                    continue
                seen_pgids.add(pgid)
                pg_cdn_n = cdn_url_map_name.get(pgid, {})
                pg_label = pg_cdn_n.get("label") or pgid_to_label.get(pgid, f"news {page_num}")
                pg_url   = f"{base_av_url}?eid={found_eid}&edate={edate_enc}&pgid={pgid}"
                log.info(f"[DT-NAME] Navigating to pgid={pgid} ({pg_label!r})")
                try:
                    page.goto(pg_url, wait_until="domcontentloaded", timeout=20000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    page.wait_for_timeout(800)

                    # Skip screenshot when CDN URL exists (saves ~1.5s per page)
                    pg_shot = "" if (pg_cdn_n.get("xhighres") or pg_cdn_n.get("highres")) else _take_shot_name()

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
                        "pgid":          pgid,
                        "label":         pg_label,
                        "articles":      new_arts,
                        "screenshot_b64": pg_shot,
                        "highres_url":   pg_cdn_n.get("xhighres") or pg_cdn_n.get("highres") or "",
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
            "highres_url":    pg.get("highres_url", ""),
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
        pdf_bytes = _build_pdf_from_articles(
            articles, page_url, date_str,
            screenshots or None,
            pages=result.get("pages", []),
        )
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


# ── Page-images PDF endpoint ──────────────────────────────────────────────────

class PageImagesItem(BaseModel):
    url: str
    label: str = ""


class PageImagesPdfRequest(BaseModel):
    pages: list[PageImagesItem]
    filename: str = "pages.pdf"


@router.post("/page-images-pdf")
async def download_page_images_pdf(body: PageImagesPdfRequest):
    """
    Download one or more newspaper page images (from CDN highres_url) and
    assemble them into a single downloadable PDF.
    No authentication required — CloudFront CDN URLs are public.
    """
    import base64 as _b64

    items = [p for p in body.pages if p.url.strip()]
    if not items:
        raise HTTPException(status_code=400, detail="No page URLs provided")

    # Download images concurrently via httpx
    async def _fetch_image(item: PageImagesItem) -> tuple[str, bytes | None]:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(item.url.strip(), headers=HEADERS)
                resp.raise_for_status()
                return item.label, resp.content
        except Exception:
            return item.label, None

    import asyncio as _aio
    results = await _aio.gather(*[_fetch_image(it) for it in items])

    # Build PDF with fpdf2
    from fpdf import FPDF

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)

    page_w_mm = 210.0
    page_h_mm = 297.0

    any_added = False
    for label, img_bytes in results:
        if not img_bytes:
            continue
        pdf.add_page()
        # Write image to temp in-memory stream
        import io as _io
        img_stream = _io.BytesIO(img_bytes)
        try:
            # fpdf2 can read from BytesIO
            pdf.image(img_stream, x=0, y=0, w=page_w_mm, h=page_h_mm, keep_aspect_ratio=True)
        except Exception:
            # If image fails, just leave blank page
            pass
        if label:
            pdf.set_xy(0, page_h_mm - 8)
            pdf.set_font("Helvetica", size=8)
            pdf.cell(page_w_mm, 8, txt=label[:120], align="C")
        any_added = True

    if not any_added:
        raise HTTPException(status_code=502, detail="Could not download any page images from CDN")

    pdf_bytes = pdf.output()
    fname = body.filename.strip() or "pages.pdf"
    if not fname.endswith(".pdf"):
        fname += ".pdf"
    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
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


# ── Classifieds Images endpoint ───────────────────────────────────────────────

_EPAPER_BASE = "https://epaper.dailythanthi.com"
_CLASSIFIED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://epaper.dailythanthi.com/",
}


@router.get("/classifieds-images")
async def get_classifieds_images(
    pgid: str = "",
    source_url: str = "",
):
    """
    Fetch classified ad images for a given page ID.

    pgid:       Page ID extracted from ArticleView URL (e.g. 101846969)
    source_url: Full ArticleView URL — pgid parsed automatically
                e.g. https://epaper.dailythanthi.com/Home/ArticleView?eid=77&edate=16/03/2026&pgid=101846969

    Flow:
      1. Call getingRectangleObject?pageid={pgid}  → list of page objects
      2. Filter ObjectType == 4  (images)
      3. For each ObjectId call getpicturedetail?Pic_id={ObjectId}
      4. Return list of { pic_id, image_url }
    """
    import logging
    log = logging.getLogger(__name__)

    resolved_pgid = pgid.strip()

    if source_url.strip() and not resolved_pgid:
        from urllib.parse import parse_qs as _pqs
        _qs = _pqs(urlparse(source_url.strip()).query)
        resolved_pgid = (_qs.get("pgid") or _qs.get("Pgid") or [""])[0].strip()

    if not resolved_pgid:
        raise HTTPException(status_code=400, detail="pgid is required")

    rect_url = f"{_EPAPER_BASE}/Home/getingRectangleObject?pageid={resolved_pgid}"

    try:
        async with httpx.AsyncClient(headers=_CLASSIFIED_HEADERS, timeout=30) as client:
            rect_resp = await client.get(rect_url)
            rect_resp.raise_for_status()
            objects = rect_resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch page objects: {exc}")

    pic_ids = [
        item["ObjectId"]
        for item in (objects if isinstance(objects, list) else [])
        if item.get("ObjectType") == 4
    ]
    log.info(f"[CLASSIFIEDS] pgid={resolved_pgid} — found {len(pic_ids)} images")

    images = []
    async with httpx.AsyncClient(headers=_CLASSIFIED_HEADERS, timeout=30) as client:
        for pid in pic_ids:
            detail_url = f"{_EPAPER_BASE}/Home/getpicturedetail?Pic_id={pid}"
            try:
                det = await client.get(detail_url)
                det.raise_for_status()
                detail = det.json()
                img_url = detail.get("ImagePath", "").replace("\\", "/")
                if img_url:
                    images.append({"pic_id": pid, "image_url": img_url})
            except Exception as exc:
                log.warning(f"[CLASSIFIEDS] pic_id={pid} detail failed: {exc}")

    return {
        "pgid": resolved_pgid,
        "total_images": len(images),
        "images": images,
    }


# ── Classifieds OCR → PDF ─────────────────────────────────────────────────────

class ClassifiedsOcrRequest(BaseModel):
    images: list[dict]   # [{"pic_id": str, "image_url": str}, ...]
    pgid: str = ""


@router.post("/classifieds-ocr-pdf")
async def classifieds_ocr_pdf(request: ClassifiedsOcrRequest):
    """
    Download each classified ad image, extract text via Tesseract OCR (local, free),
    and return a single PDF with all extracted text (one page per image).
    """
    import logging
    import os, shutil
    import pytesseract
    from PIL import Image
    from core.config import get_settings

    log = logging.getLogger(__name__)
    _ocr_key = get_settings().ocr_space_api_key

    if not _ocr_key:
        # Local: configure Tesseract path
        if os.name == "nt":
            pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        else:
            tesseract_bin = shutil.which("tesseract") or "/usr/bin/tesseract"
            pytesseract.pytesseract.tesseract_cmd = tesseract_bin

    if not request.images:
        raise HTTPException(status_code=400, detail="No images provided")

    results: list[dict] = []

    async with httpx.AsyncClient(headers=_CLASSIFIED_HEADERS, timeout=30) as http:
        for img in request.images:
            pic_id    = str(img.get("pic_id", ""))
            image_url = str(img.get("image_url", ""))
            if not image_url:
                continue

            # Download image
            try:
                img_resp = await http.get(image_url)
                img_resp.raise_for_status()
                img_bytes = img_resp.content
            except Exception as exc:
                log.warning(f"[OCR] download failed pic_id={pic_id}: {exc}")
                results.append({"pic_id": pic_id, "text": f"(Image download failed: {exc})"})
                continue

            if _ocr_key:
                # Production (Render): use OCR.space API directly
                try:
                    log.info(f"[OCR] Using OCR.space API for pic_id={pic_id}")
                    ocr_resp = await http.post(
                        "https://api.ocr.space/parse/image",
                        data={"apikey": _ocr_key, "language": "tam", "isOverlayRequired": "false"},
                        files={"file": ("image.jpg", img_bytes, "image/jpeg")},
                        timeout=30,
                    )
                    ocr_data = ocr_resp.json()
                    parsed = ocr_data.get("ParsedResults", [])
                    ocr_text = parsed[0].get("ParsedText", "").strip() if parsed else ""
                    ocr_text = ocr_text or "(No text found)"
                    log.info(f"[OCR] OCR.space success pic_id={pic_id} — {len(ocr_text)} chars")
                except Exception as exc:
                    log.warning(f"[OCR] OCR.space failed pic_id={pic_id}: {exc}")
                    ocr_text = f"(OCR failed: {exc})"
            else:
                # Local: use Tesseract
                try:
                    pil_img  = await asyncio.to_thread(lambda b: Image.open(io.BytesIO(b)), img_bytes)
                    ocr_text = await asyncio.to_thread(
                        pytesseract.image_to_string, pil_img, lang="tam+eng"
                    )
                    ocr_text = ocr_text.strip() or "(No text found)"
                except Exception as exc:
                    log.warning(f"[OCR] Tesseract failed pic_id={pic_id}: {exc}")
                    ocr_text = f"(OCR failed: {exc})"

            results.append({"pic_id": pic_id, "text": ocr_text})
            log.info(f"[OCR] pic_id={pic_id} — {len(ocr_text)} chars extracted")

    # ── Build PDF via Playwright (correct Tamil shaping) ───────────────────────
    import html as _html

    pages_html = ""
    for i, item in enumerate(results):
        heading  = _html.escape(f"Image {i + 1}  —  pic_id: {item['pic_id']}")
        body_txt = _html.escape(item["text"])
        pages_html += (
            f'<div class="pg">'
            f'<h2>{heading}</h2>'
            f'<pre>{body_txt}</pre>'
            f'</div>'
        )

    full_html = f"""<!DOCTYPE html>
<html lang="ta">
<head>
<meta charset="UTF-8"/>
<style>
  body {{
    font-family: "Nirmala UI", "Latha", "Arial Unicode MS", sans-serif;
    font-size: 11pt;
    margin: 0;
    padding: 0;
    color: #111;
  }}
  .pg {{
    padding: 32px 40px 24px;
    page-break-after: always;
  }}
  h2 {{
    font-size: 13pt;
    font-weight: bold;
    margin-bottom: 12px;
    border-bottom: 1px solid #ccc;
    padding-bottom: 6px;
  }}
  pre {{
    font-family: "Nirmala UI", "Latha", "Arial Unicode MS", sans-serif;
    font-size: 11pt;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.7;
    margin: 0;
  }}
</style>
</head>
<body>{pages_html}</body>
</html>"""

    def _render_pdf(html_str: str) -> bytes:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            pg      = browser.new_page()
            pg.set_content(html_str, wait_until="domcontentloaded")
            data = pg.pdf(
                format="A4",
                margin={"top": "0px", "bottom": "0px", "left": "0px", "right": "0px"},
                print_background=True,
            )
            browser.close()
        return data

    try:
        pdf_bytes = await asyncio.to_thread(_render_pdf, full_html)
    except Exception as exc:
        import traceback
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}\n{traceback.format_exc()}")

    filename = f"classifieds_ocr_{request.pgid or 'extract'}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Tenders Images ────────────────────────────────────────────────────────────

@router.get("/tenders-images")
async def get_tenders_images(
    pgid: str = "",
    source_url: str = "",
):
    """
    Fetch tender notice images for a given page ID.
    Same flow as classifieds-images — filters ObjectType == 4.
    """
    import logging
    log = logging.getLogger(__name__)

    resolved_pgid = pgid.strip()

    if source_url.strip() and not resolved_pgid:
        from urllib.parse import parse_qs as _pqs
        _qs = _pqs(urlparse(source_url.strip()).query)
        resolved_pgid = (_qs.get("pgid") or _qs.get("Pgid") or [""])[0].strip()

    if not resolved_pgid:
        raise HTTPException(status_code=400, detail="pgid is required")

    rect_url = f"{_EPAPER_BASE}/Home/getingRectangleObject?pageid={resolved_pgid}"

    try:
        async with httpx.AsyncClient(headers=_CLASSIFIED_HEADERS, timeout=30) as client:
            rect_resp = await client.get(rect_url)
            rect_resp.raise_for_status()
            objects = rect_resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch page objects: {exc}")

    pic_ids = [
        item["ObjectId"]
        for item in (objects if isinstance(objects, list) else [])
        if item.get("ObjectType") == 4
    ]
    log.info(f"[TENDERS] pgid={resolved_pgid} — found {len(pic_ids)} images")

    images = []
    async with httpx.AsyncClient(headers=_CLASSIFIED_HEADERS, timeout=30) as client:
        for pid in pic_ids:
            detail_url = f"{_EPAPER_BASE}/Home/getpicturedetail?Pic_id={pid}"
            try:
                det = await client.get(detail_url)
                det.raise_for_status()
                detail = det.json()
                img_url = detail.get("ImagePath", "").replace("\\", "/")
                if img_url:
                    images.append({"pic_id": pid, "image_url": img_url})
            except Exception as exc:
                log.warning(f"[TENDERS] pic_id={pid} detail failed: {exc}")

    return {
        "pgid": resolved_pgid,
        "total_images": len(images),
        "images": images,
    }


# ── Tenders OCR → PDF ─────────────────────────────────────────────────────────

class TendersOcrRequest(BaseModel):
    images: list[dict]   # [{"pic_id": str, "image_url": str}, ...]
    pgid: str = ""


@router.post("/tenders-ocr-pdf")
async def tenders_ocr_pdf(request: TendersOcrRequest):
    """
    Download each tender notice image, extract text via OCR,
    and return a single PDF with all extracted text (one page per image).
    """
    import logging
    import os, shutil
    import pytesseract
    from PIL import Image
    from core.config import get_settings

    log = logging.getLogger(__name__)
    _ocr_key = get_settings().ocr_space_api_key

    if not _ocr_key:
        if os.name == "nt":
            pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        else:
            tesseract_bin = shutil.which("tesseract") or "/usr/bin/tesseract"
            pytesseract.pytesseract.tesseract_cmd = tesseract_bin

    if not request.images:
        raise HTTPException(status_code=400, detail="No images provided")

    results: list[dict] = []

    async with httpx.AsyncClient(headers=_CLASSIFIED_HEADERS, timeout=30) as http:
        for img in request.images:
            pic_id    = str(img.get("pic_id", ""))
            image_url = str(img.get("image_url", ""))
            if not image_url:
                continue

            try:
                img_resp = await http.get(image_url)
                img_resp.raise_for_status()
                img_bytes = img_resp.content
            except Exception as exc:
                log.warning(f"[TENDERS OCR] download failed pic_id={pic_id}: {exc}")
                results.append({"pic_id": pic_id, "text": f"(Image download failed: {exc})"})
                continue

            if _ocr_key:
                try:
                    log.info(f"[TENDERS OCR] Using OCR.space API for pic_id={pic_id}")
                    ocr_resp = await http.post(
                        "https://api.ocr.space/parse/image",
                        data={"apikey": _ocr_key, "language": "tam", "isOverlayRequired": "false"},
                        files={"file": ("image.jpg", img_bytes, "image/jpeg")},
                        timeout=30,
                    )
                    ocr_data = ocr_resp.json()
                    parsed = ocr_data.get("ParsedResults", [])
                    ocr_text = parsed[0].get("ParsedText", "").strip() if parsed else ""
                    ocr_text = ocr_text or "(No text found)"
                    log.info(f"[TENDERS OCR] OCR.space success pic_id={pic_id} — {len(ocr_text)} chars")
                except Exception as exc:
                    log.warning(f"[TENDERS OCR] OCR.space failed pic_id={pic_id}: {exc}")
                    ocr_text = f"(OCR failed: {exc})"
            else:
                try:
                    pil_img  = await asyncio.to_thread(lambda b: Image.open(io.BytesIO(b)), img_bytes)
                    ocr_text = await asyncio.to_thread(
                        pytesseract.image_to_string, pil_img, lang="tam+eng"
                    )
                    ocr_text = ocr_text.strip() or "(No text found)"
                except Exception as exc:
                    log.warning(f"[TENDERS OCR] Tesseract failed pic_id={pic_id}: {exc}")
                    ocr_text = f"(OCR failed: {exc})"

            results.append({"pic_id": pic_id, "text": ocr_text})
            log.info(f"[TENDERS OCR] pic_id={pic_id} — {len(ocr_text)} chars extracted")

    import html as _html

    pages_html = ""
    for i, item in enumerate(results):
        heading  = _html.escape(f"Image {i + 1}  —  pic_id: {item['pic_id']}")
        body_txt = _html.escape(item["text"])
        pages_html += (
            f'<div class="pg">'
            f'<h2>{heading}</h2>'
            f'<pre>{body_txt}</pre>'
            f'</div>'
        )

    full_html = f"""<!DOCTYPE html>
<html lang="ta">
<head>
<meta charset="UTF-8"/>
<style>
  body {{
    font-family: "Nirmala UI", "Latha", "Arial Unicode MS", sans-serif;
    font-size: 11pt;
    margin: 0;
    padding: 0;
    color: #111;
  }}
  .pg {{
    padding: 32px 40px 24px;
    page-break-after: always;
  }}
  h2 {{
    font-size: 13pt;
    font-weight: bold;
    margin-bottom: 12px;
    border-bottom: 1px solid #ccc;
    padding-bottom: 6px;
  }}
  pre {{
    font-family: "Nirmala UI", "Latha", "Arial Unicode MS", sans-serif;
    font-size: 11pt;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.7;
    margin: 0;
  }}
</style>
</head>
<body>{pages_html}</body>
</html>"""

    def _render_pdf(html_str: str) -> bytes:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            pg      = browser.new_page()
            pg.set_content(html_str, wait_until="domcontentloaded")
            data = pg.pdf(
                format="A4",
                margin={"top": "0px", "bottom": "0px", "left": "0px", "right": "0px"},
                print_background=True,
            )
            browser.close()
        return data

    try:
        pdf_bytes = await asyncio.to_thread(_render_pdf, full_html)
    except Exception as exc:
        import traceback
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}\n{traceback.format_exc()}")

    filename = f"tenders_ocr_{request.pgid or 'extract'}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

