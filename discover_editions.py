#!/usr/bin/env python3
"""
Discover Daily Thanthi e-paper Edition IDs (EIDs) for ALL districts.

Strategy (3-layer):
  1. After login, scan every <a href="…eid=X"> on the post-login page.
  2. Intercept all JSON API responses — if the site calls an edition-list API,
     we capture it automatically.
  3. Open the "Select Edition" modal, iterate over every edition button,
     click each one, and capture the EID from the resulting URL.

Saves results → editions_map.json  (used automatically by gen_html.py).

Run once (takes 5–10 minutes for all 47 editions):
    python discover_editions.py

A visible browser window opens so you can watch the progress.
"""
import json, os, re
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

BASE     = r'C:\Users\Dell\Downloads\E-scrapper'
ENV_PATH = os.path.join(BASE, 'backend', '.env')
OUT_PATH = os.path.join(BASE, 'editions_map.json')

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Pre-seeded known EIDs — always correct
KNOWN = {'Madurai': '77'}

# Our 47 known edition names (for matching against modal text)
KNOWN_NAMES = [
    "Andhra", "Bengaluru", "Chengalpattu", "Chennai City",
    "Chidambaram & Virudhachalam", "Coimbatore", "Colombo", "Cuddalore",
    "Dharampuri", "Dindigul", "Dindigul District", "Dubai", "Erode", "Hosur",
    "Kancheepuram", "Karur", "Kerala & Theni", "Kerala Coimbatore",
    "Kerala Nagarcoil", "Krishnagiri", "Kumbakonam & Pattukottai",
    "Kunnatur, Ch.Palli, U.Kuli", "Madurai", "Mangalore & Raichur", "Mumbai",
    "Mysore & KGF", "Nagai & Karaikal", "Nagarcoil", "Namakkal", "Nilgiris",
    "Pondicherry", "Pudukkottai", "Ramnad & Sivagangai",
    "Ranipet & Tirupathur District", "Salem City", "Salem District", "Tanjore",
    "Thoothukudi District", "Tirunelveli District", "Tirupur", "Tirupur District",
    "Tiruvallur", "Tiruvannamalai", "Tiruvarur", "Vellore", "Villupuram",
    "Virudhunagar",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _read_env(path):
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    except Exception as e:
        print(f"  Warning reading env: {e}")
    return env


def _eid_from_url(url_str):
    try:
        return parse_qs(urlparse(url_str).query).get('eid', [''])[0]
    except Exception:
        return ''


def _fill_login(page, email, password):
    try:
        result = page.evaluate(
            """([em, pw]) => {
                const all = Array.from(document.querySelectorAll('input'));
                const passEl = all.find(i => i.type === 'password');
                if (!passEl) return 'NO_PASS';
                const SKIP = ['hidden','submit','button','checkbox','radio','file','image','reset'];
                const emailEl = all.find(i => i !== passEl && !SKIP.includes(i.type));
                if (!emailEl) return 'NO_EMAIL';
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(emailEl, em);
                setter.call(passEl, pw);
                ['input','change'].forEach(ev => {
                    emailEl.dispatchEvent(new Event(ev, {bubbles:true}));
                    passEl.dispatchEvent(new Event(ev, {bubbles:true}));
                });
                const form = passEl.closest('form');
                const btn = form && (
                    form.querySelector('#btnLogin') ||
                    form.querySelector('[type="submit"]') ||
                    form.querySelector('button[type="submit"]') ||
                    form.querySelector('button')
                );
                if (btn) { btn.click(); return 'CLICKED'; }
                if (form) { form.submit(); return 'SUBMITTED'; }
                return 'NO_BTN';
            }""",
            [email, password],
        )
        return result not in ('NO_PASS', 'NO_EMAIL')
    except Exception as e:
        print(f"  Login error: {e}")
        return False


def _dismiss_dialog(page):
    for _ in range(8):
        try:
            r = page.evaluate("""
                () => {
                    const body = document.body?.innerText || '';
                    if (!body.includes('already logged in')) return null;
                    const yes = Array.from(document.querySelectorAll('button,a')).find(
                        el => (el.textContent||'').trim() === 'Yes'
                             && getComputedStyle(el).display !== 'none'
                    );
                    if (yes) { yes.click(); return 'YES'; }
                    return 'WAIT';
                }
            """)
            if r == 'YES':
                page.wait_for_timeout(1500)
                return
        except Exception:
            pass
        page.wait_for_timeout(500)


def _click_edition_selector(page):
    """Try every known selector for the Select Edition button. Returns True if clicked."""
    selectors = [
        "#selectEdition", ".selectEdition", ".selectEditionbtn", "#selectEditionbtn",
        "[data-target*='edition' i]", "[data-toggle*='modal'][href*='edition' i]",
        "a:has-text('Select Edition')", "button:has-text('Select Edition')",
        "a:has-text('edition')", "button:has-text('edition')",
        ".edition-select", "#edition-select", ".editionSelect", "#editionSelect",
        "[onclick*='edition' i]", "[class*='edition' i][role='button']",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                el.click()
                page.wait_for_timeout(2000)
                print(f"  Clicked edition selector: {sel}")
                return True
        except Exception:
            pass
    return False


def _get_edition_items(page):
    """Collect text+href for all visible edition-like items."""
    return page.evaluate("""
        () => {
            const seen = new Set();
            const result = [];
            const containers = [
                '.modal-body', '.modal-content', '.dropdown-menu',
                '[class*="edition" i]', '[id*="edition" i]',
                '.modal', '#editionModal', '#selectEditionModal',
            ];
            let source = null;
            for (const sel of containers) {
                source = document.querySelector(sel);
                if (source) break;
            }
            if (!source) source = document.body;

            const els = Array.from(source.querySelectorAll('a, button, li, div[onclick], span[onclick]'));
            for (const el of els) {
                const text = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                if (!text || text.length < 2 || text.length > 80) continue;
                if (seen.has(text)) continue;
                seen.add(text);
                result.push({
                    text,
                    href: el.href || '',
                    onclick: el.getAttribute('onclick') || '',
                    tag: el.tagName,
                });
            }
            return result;
        }
    """)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    env      = _read_env(ENV_PATH)
    EMAIL    = env.get('EPAPER_EMAIL', '')
    PASSWORD = env.get('EPAPER_PASSWORD', '')
    BASE_URL = env.get('EPAPER_BASE_URL', 'https://epaper.dailythanthi.com')

    if not EMAIL or not PASSWORD:
        print("ERROR: EPAPER_EMAIL and EPAPER_PASSWORD not found in backend/.env")
        return

    eid_map = dict(KNOWN)
    api_responses = []   # captured JSON responses from the website
    nav_eids = {}        # eid values seen in request URLs

    print("=" * 60)
    print("Daily Thanthi — Edition ID Discovery")
    print(f"Email   : {EMAIL}")
    print(f"Output  : {OUT_PATH}")
    print("=" * 60)
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,   # visible so you can see what's happening
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        # ── Intercept network: capture EIDs and JSON responses ────────────────
        def on_request(req):
            u = req.url
            if 'eid=' in u or 'ArticleView' in u:
                eid = _eid_from_url(u)
                if eid:
                    nav_eids[u] = eid

        def on_response(resp):
            try:
                ct = resp.headers.get('content-type', '')
                if 'json' in ct:
                    data = resp.json()
                    api_responses.append({'url': resp.url, 'data': data})
            except Exception:
                pass

        page.on('request', on_request)
        page.on('response', on_response)

        # ── Step 1: Login ─────────────────────────────────────────────────────
        login_url = BASE_URL.rstrip('/') + '/Login/Landingpage'
        print(f"[1] Logging in → {login_url}")
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"    Warning: {e}")
        page.wait_for_timeout(2000)

        ok = _fill_login(page, EMAIL, PASSWORD)
        print(f"    Form submit: {'OK' if ok else 'FAILED'}")
        _dismiss_dialog(page)

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        print(f"    Post-login URL: {page.url}")

        # ── Step 2: Scan post-login page for eid= links ───────────────────────
        print("\n[2] Scanning page for eid= links...")
        found = page.evaluate("""
            () => {
                const seen = new Set(), res = [];
                document.querySelectorAll('a[href*="eid="]').forEach(a => {
                    try {
                        const url = new URL(a.href, location.origin);
                        const eid = url.searchParams.get('eid');
                        if (eid && !seen.has(eid)) {
                            seen.add(eid);
                            const name = (a.textContent || a.title || '').trim().replace(/\\s+/g, ' ');
                            res.push({name, eid});
                        }
                    } catch(_) {}
                });
                return res;
            }
        """)
        for item in found:
            if item['name'] and item['eid']:
                eid_map[item['name']] = item['eid']
                print(f"    Link found: {item['name']} → EID {item['eid']}")

        # ── Step 3: Scan JavaScript source for embedded edition data ──────────
        print("\n[3] Scanning JavaScript for EID patterns...")
        js_src = page.evaluate("""
            () => Array.from(document.querySelectorAll('script:not([src])')).map(s => s.textContent).join('\\n')
        """)
        # Pattern: "editionName":"Madurai","eid":"77"  or  {name:'Madurai',eid:77}
        for m in re.finditer(
            r'"?(?:editionname|editionName|EditionName|name|Name)"?\s*:\s*"([^"]+)"[^}]{0,80}?"?[Ee]id"?\s*:\s*"?(\d+)',
            js_src
        ):
            name, eid = m.group(1).strip(), m.group(2)
            eid_map[name] = eid
            print(f"    JS data: {name} → EID {eid}")

        # ── Step 4: Open the Select Edition modal ─────────────────────────────
        print("\n[4] Opening Select Edition modal...")
        clicked = _click_edition_selector(page)
        if not clicked:
            print("    Could not find the Select Edition button automatically.")
            print("    Please MANUALLY click 'Select Edition' in the browser window.")
            page.wait_for_timeout(8000)   # give the user time to click manually

        # ── Step 5: Extract edition names from the modal ──────────────────────
        print("\n[5] Extracting edition items from the modal...")
        items = _get_edition_items(page)
        print(f"    Found {len(items)} candidate items")

        # Filter to items that look like edition names
        edition_items = []
        for item in items:
            txt = item['text']
            eid = _eid_from_url(item['href'])
            if eid:
                # Already has EID in href — take it directly
                eid_map[txt] = eid
                print(f"    Direct EID from href: {txt} → {eid}")
            else:
                # Check if the text matches one of our known edition names (fuzzy)
                for known in KNOWN_NAMES:
                    if known.lower() in txt.lower() or txt.lower() in known.lower():
                        edition_items.append({'text': txt, 'canonical': known})
                        break
                else:
                    # Also include items that look like city/district names
                    if any(txt in name or name in txt for name in KNOWN_NAMES):
                        edition_items.append({'text': txt, 'canonical': txt})

        print(f"    Edition-like items to click: {len(edition_items)}")

        # ── Step 6: Click each edition and capture EID from resulting URL ──────
        print("\n[6] Clicking through editions to capture EIDs...")
        print("    (This takes ~5 minutes — browser window shows the progress)\n")

        for i, item in enumerate(edition_items):
            name = item['text']
            canonical = item['canonical']
            if canonical in eid_map and eid_map[canonical] != '??':
                print(f"    [{i+1}/{len(edition_items)}] {name!r} — already known EID {eid_map[canonical]}, skipping")
                continue

            print(f"    [{i+1}/{len(edition_items)}] Clicking: {name!r}", end=" → ", flush=True)

            # Re-open the modal if it closed
            try:
                modal_visible = page.evaluate("""
                    () => {
                        const m = document.querySelector('.modal.show, .modal-overlay.open, [id*="edition"][style*="block"]');
                        return !!m;
                    }
                """)
                if not modal_visible:
                    _click_edition_selector(page)
                    page.wait_for_timeout(1500)
            except Exception:
                _click_edition_selector(page)
                page.wait_for_timeout(1500)

            prev_url = page.url
            try:
                # Click the edition item by text
                found = page.evaluate(
                    """(name) => {
                        const containers = ['.modal-body','.modal','.dropdown-menu','[class*="edition" i]','body'];
                        for (const sel of containers) {
                            const c = document.querySelector(sel);
                            if (!c) continue;
                            const els = Array.from(c.querySelectorAll('a,button,li,div,span'));
                            const match = els.find(el => (el.textContent||'').trim().replace(/\\s+/g,' ') === name);
                            if (match) { match.click(); return true; }
                        }
                        return false;
                    }""",
                    name,
                )

                if found:
                    # Wait for navigation or URL change
                    page.wait_for_timeout(4000)
                    new_url = page.url
                    new_eid = _eid_from_url(new_url)

                    if new_eid and new_url != prev_url:
                        eid_map[canonical] = new_eid
                        print(f"EID {new_eid}")
                    else:
                        # Check intercepted request URLs for a new eid
                        for req_url, req_eid in nav_eids.items():
                            if req_eid not in eid_map.values() or req_eid == new_eid:
                                # best guess — associate with the edition we just clicked
                                eid_map[canonical] = req_eid
                                print(f"EID {req_eid} (from intercepted request)")
                                break
                        else:
                            print("not found (URL did not change)")
                else:
                    print("item not clickable")

            except Exception as ex:
                print(f"error: {ex}")

        # ── Step 7: Mine captured API responses ───────────────────────────────
        print(f"\n[7] Mining {len(api_responses)} captured API responses...")
        for resp in api_responses:
            data = resp['data']
            items_list = data if isinstance(data, list) else []
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        items_list = v
                        break
            for item in items_list:
                if not isinstance(item, dict):
                    continue
                eid_val  = str(item.get('eid') or item.get('Eid') or item.get('EId') or item.get('editionId') or '')
                name_val = str(item.get('editionName') or item.get('EditionName') or item.get('name') or item.get('Name') or '')
                if eid_val.isdigit() and name_val:
                    if name_val not in eid_map:
                        eid_map[name_val] = eid_val
                        print(f"    API ({resp['url'].split('/')[-1]}): {name_val} → EID {eid_val}")

        browser.close()

    # ── Save results ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"TOTAL EIDs DISCOVERED: {len(eid_map)}")
    print()
    for name in sorted(eid_map.keys()):
        marker = "" if eid_map[name].isdigit() else " ← abbreviation (not real EID)"
        print(f"  {name:45s} {eid_map[name]}{marker}")

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(eid_map, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"\nSaved → {OUT_PATH}")
    print("Next step: python gen_html.py   (to regenerate the HTML with all EIDs)")


if __name__ == '__main__':
    main()
