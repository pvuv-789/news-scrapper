"""
Debug script: logs into Daily Thanthi epaper and inspects article DOM structure.
"""
import asyncio
from playwright.async_api import async_playwright
from core.config import get_settings

settings = get_settings()
BASE_URL = settings.epaper_base_url
EMAIL = settings.epaper_email
PASSWORD = settings.epaper_password

# Article URL shared by user — used to inspect real article DOM
ARTICLE_URL = "https://epaper.dailythanthi.com/Home/ArticleView?eid=77&edate=26/02/2026&pgid=101834098"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # Step 1: Go to homepage
        print("Step 1: Navigating to homepage...")
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.screenshot(path="debug_01_homepage.png")

        # Step 2: Click the login button to open the login modal
        print("Step 2: Looking for login trigger button...")
        login_triggers = [
            "a:has-text('Login')",
            "a:has-text('Sign In')",
            "button:has-text('Login')",
            ".login",
            "#loginBtn",
            "a[href*='Login']",
            "a[href*='login']",
        ]
        clicked = False
        for sel in login_triggers:
            try:
                el = await page.query_selector(sel)
                if el:
                    print(f"  Clicking: {sel}")
                    await el.click()
                    await page.wait_for_timeout(1500)
                    clicked = True
                    break
            except:
                continue

        await page.screenshot(path="debug_02_login_modal.png")
        if not clicked:
            print("  Could not find login trigger. Saving HTML...")
            html = await page.content()
            with open("debug_homepage.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  Saved: debug_homepage.html — inspect to find login button selector")

        # Step 3: Fill login credentials
        print("Step 3: Filling login credentials...")
        login_fields = [
            ("#txtUserName", "#txtPassword"),
            ("#txtEmail",    "#txtPassword"),
            ("#txtNumber1",  "#txtPassword"),
            ("input[name='UserName']", "input[name='Password']"),
            ("input[type='email']",    "input[type='password']"),
        ]
        logged_in = False
        for email_sel, pass_sel in login_fields:
            try:
                email_el = await page.query_selector(email_sel)
                pass_el  = await page.query_selector(pass_sel)
                if email_el and pass_el:
                    if await email_el.is_visible() and await pass_el.is_visible():
                        await email_el.fill(EMAIL)
                        await pass_el.fill(PASSWORD)
                        print(f"  Filled: {email_sel} / {pass_sel}")
                        logged_in = True
                        break
            except:
                continue

        if not logged_in:
            # Save page HTML to inspect login form
            html = await page.content()
            with open("debug_login_modal.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  Could not fill form. Saved: debug_login_modal.html")

        await page.screenshot(path="debug_03_filled.png")

        # Step 4: Submit login form
        print("Step 4: Submitting login...")
        submit_selectors = [
            "#btnLogin",
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('LOGIN')",
            "button:has-text('Login')",
            "a:has-text('LOGIN')",
        ]
        for sel in submit_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    print(f"  Clicked submit: {sel}")
                    break
            except:
                continue

        await page.wait_for_timeout(3000)
        await page.screenshot(path="debug_04_after_login.png")
        print(f"  URL after login: {page.url}")

        # Step 5: Navigate to the known article URL
        print(f"\nStep 5: Navigating to article URL...")
        await page.goto(ARTICLE_URL, wait_until="networkidle")
        await page.wait_for_timeout(2000)
        await page.screenshot(path="debug_05_article.png")
        print(f"  URL: {page.url}")

        html = await page.content()
        with open("debug_article.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("  Saved: debug_article.html")

        # Step 6: Also try Home/Index after login
        print("\nStep 6: Navigating to Home/Index...")
        await page.goto(BASE_URL + "/Home/Index", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        await page.screenshot(path="debug_06_home_index.png")
        html2 = await page.content()
        with open("debug_home_index.html", "w", encoding="utf-8") as f:
            f.write(html2)
        print("  Saved: debug_home_index.html")
        print(f"  URL: {page.url}")

        print("\n✅ Done. Check screenshots and HTML files in the backend folder.")
        input("Press Enter to close browser...")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
