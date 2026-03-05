"""
Web Scraper → PDF Exporter
--------------------------
Scrapes any webpage and exports the content as a formatted PDF report.

Usage:
    python scrape_to_pdf.py <url> [output.pdf]

Examples:
    python scrape_to_pdf.py https://news.ycombinator.com
    python scrape_to_pdf.py https://example.com/article  my_report.pdf
"""

import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fpdf import FPDF

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── Scraping ──────────────────────────────────────────────────────────────────

def scrape_page(url: str) -> dict:
    """Fetch a URL and extract structured content."""
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        response = client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove noisy tags
    for tag in soup(["script", "style", "noscript", "nav", "footer", "aside", "iframe"]):
        tag.decompose()

    # Title
    title = ""
    if soup.title:
        title = soup.title.get_text(strip=True)
    if not title and soup.find("h1"):
        title = soup.find("h1").get_text(strip=True)
    if not title:
        title = urlparse(url).netloc

    # Meta description
    meta_desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta:
        meta_desc = meta.get("content", "").strip()

    # Published date (common meta tags)
    published = ""
    for attr in ["article:published_time", "datePublished", "pubdate", "date"]:
        tag = (
            soup.find("meta", attrs={"property": attr})
            or soup.find("meta", attrs={"name": attr})
        )
        if tag:
            published = tag.get("content", "").strip()
            if published:
                break
    if not published:
        time_tag = soup.find("time", attrs={"datetime": True})
        if time_tag:
            published = time_tag["datetime"].strip()

    # Content blocks: headings + paragraphs + lists
    content_blocks = []
    main = soup.find("main") or soup.find("article") or soup.find("body")
    if main:
        for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
            text = el.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            if not text or len(text) < 8:
                continue
            content_blocks.append({"tag": el.name, "text": text})

    # Collect links (up to 40)
    links = []
    seen_hrefs: set[str] = set()
    for a in soup.find_all("a", href=True):
        label = a.get_text(strip=True)
        href = a["href"]
        if not href.startswith("http"):
            href = urljoin(url, href)
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
        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "content_blocks": content_blocks,
        "links": links,
    }


# ── PDF Generation ────────────────────────────────────────────────────────────

class ScraperPDF(FPDF):
    """Custom FPDF subclass with header/footer."""

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


def _safe_text(text: str) -> str:
    """Replace characters outside latin-1 range that FPDF can't encode."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


def build_pdf(data: dict, output_path: str) -> None:
    """Generate a formatted PDF from scraped page data."""
    pdf = ScraperPDF()
    pdf.set_margins(left=15, top=15, right=15)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    pw = pdf.epw  # effective page width

    # ── Cover / Meta ──────────────────────────────────────────────────────────
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(20, 30, 80)
    pdf.multi_cell(pw, 10, _safe_text(data["title"] or "Web Page Report"))
    pdf.ln(4)

    # Meta info rows
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

    # ── Content blocks ────────────────────────────────────────────────────────
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
            else:  # p
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(40, 40, 40)
                pdf.multi_cell(pw, 6, text)
                pdf.ln(2)
        except Exception:
            continue  # skip blocks that can't render

    # ── Links section ─────────────────────────────────────────────────────────
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

    pdf.output(output_path)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scrape_to_pdf.py <url> [output.pdf]")
        print("Example: python scrape_to_pdf.py https://example.com report.pdf")
        sys.exit(1)

    url = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else "scraped_output.pdf"

    print(f"\nScraping : {url}")
    try:
        data = scrape_page(url)
    except httpx.HTTPStatusError as e:
        print(f"HTTP error: {e.response.status_code} for {url}")
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Network error: {e}")
        sys.exit(1)

    print(f"  Title   : {data['title']}")
    print(f"  Blocks  : {len(data['content_blocks'])} content blocks")
    print(f"  Links   : {len(data['links'])} links")

    print(f"\nGenerating PDF → {output}")
    build_pdf(data, output)

    resolved = Path(output).resolve()
    print(f"Done! PDF saved at:\n  {resolved}")


if __name__ == "__main__":
    main()
