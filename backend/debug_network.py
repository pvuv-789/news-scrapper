"""
Intercepts network requests while clicking on an article to find
the exact API endpoint that loads article text content.
"""
import asyncio
from playwright.async_api import async_playwright
from core.config import get_settings

settings = get_settings()
BASE_URL = settings.epaper_base_url
EMAIL = settings.epaper_email
PASSWORD = settings.epaper_password

ARTICLE_URL = "https://epaper.dailythanthi.com/Home/ArticleView?eid=77&edate=26/02/2026&pgid=101834098"

captured_requests = []

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=300)
        context = await browser.new_context()

        page = await context.new_page()

        # Intercept all network requests
        async def on_request(request):
            url = request.url
            if any(x in url for x in ["Home/", "Story", "Article", "story", "article", "content", "text", "GetPage", "GetEdition"]):
                if "google" not in url and "analytics" not in url and "score" not in url:
                    captured_requests.append(f"REQUEST: {request.method} {url}")
                    if request.post_data:
                        captured_requests.append(f"  BODY: {request.post_data[:200]}")

        async def on_response(response):
            url = response.url
            if any(x in url for x in ["Home/", "Story", "Article", "story", "article", "content", "text", "GetPage", "GetEdition"]):
                if "google" not in url and "analytics" not in url and "score" not in url:
                    try:
                        body = await response.text()
                        if len(body) > 5 and len(body) < 50000:
                            captured_requests.append(f"RESPONSE: {url}")
                            captured_requests.append(f"  BODY: {body[:500]}")
                    except:
                        pass

        page.on("request", on_request)
        page.on("response", on_response)

        # Login
        print("Logging in...")
        await page.goto(BASE_URL, wait_until="networkidle")

        # Try to login
        try:
            # Find visible login inputs
            await page.evaluate("""
                var inputs = document.querySelectorAll('input');
                inputs.forEach(function(i) {
                    console.log(i.id + ' ' + i.name + ' ' + i.type + ' visible:' + (i.offsetParent !== null));
                });
            """)
        except:
            pass

        # Manual login helper - try multiple approaches
        logged_in = False

        # Check if already logged in
        if "Index" in page.url or "Home" in page.url:
            logged_in = True
            print("Already on home page")

        if not logged_in:
            # Try clicking login link
            for sel in ["a:has-text('Login')", "a:has-text('Sign In')", "#loginBtn", ".login-link"]:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        await page.wait_for_timeout(1500)
                        break
                except:
                    pass

            # Fill visible login fields
            for email_sel in ["#txtUserName", "input[name='UserName']", "#txtEmail", "input[type='email']"]:
                try:
                    el = await page.query_selector(email_sel)
                    if el and await el.is_visible():
                        await el.fill(EMAIL)
                        print(f"Filled email: {email_sel}")

                        pass_el = await page.query_selector("input[type='password']")
                        if pass_el and await pass_el.is_visible():
                            await pass_el.fill(PASSWORD)

                        # Submit
                        for btn_sel in ["#btnLogin", "button[type='submit']", "input[type='submit']", "button:has-text('LOGIN')"]:
                            try:
                                btn = await page.query_selector(btn_sel)
                                if btn and await btn.is_visible():
                                    await btn.click()
                                    await page.wait_for_timeout(3000)
                                    logged_in = True
                                    break
                            except:
                                pass
                        break
                except:
                    pass

        if not logged_in:
            print("Auto login failed. Please login manually in the browser window.")
            print("After logging in, press Enter here...")
            input()

        print(f"Current URL: {page.url}")

        # Navigate to article view
        print(f"\nNavigating to article: {ARTICLE_URL}")
        await page.goto(ARTICLE_URL, wait_until="networkidle")
        await page.wait_for_timeout(2000)
        print(f"Article URL loaded: {page.url}")

        # Click on the first article rectangle to trigger content loading
        print("Clicking on first article rectangle...")
        rect = await page.query_selector(".pagerectangle")
        if rect:
            await rect.click()
            print("Clicked! Waiting for content to load...")
            await page.wait_for_timeout(3000)

            # Check if headline loaded
            headline = await page.eval_on_selector("#divheadline", "el => el.innerText") if await page.query_selector("#divheadline") else ""
            body = await page.eval_on_selector("#body", "el => el.innerText") if await page.query_selector("#body") else ""
            print(f"Headline: {headline[:100]}")
            print(f"Body: {body[:200]}")
        else:
            print("No .pagerectangle found")

        # Save HTML after article click
        html = await page.content()
        with open("debug_after_click.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved: debug_after_click.html")

        await page.screenshot(path="debug_after_click.png")
        print("Screenshot: debug_after_click.png")

        # Print captured requests
        print("\n=== CAPTURED NETWORK REQUESTS ===")
        for r in captured_requests:
            print(r)

        with open("debug_network_log.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(captured_requests))
        print("\nSaved: debug_network_log.txt")

        input("\nPress Enter to close...")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
