#!/usr/bin/env python3
"""
Generate Daily Thanthi newspaper layout HTML with live edition scraping.
- Removes en-dash hyphenation markers from Tamil text.
- Adds dynamic edition-switching via the FastAPI backend.
- Reads discovered EIDs from editions_map.json if it exists.
"""
import json, re, os

BASE = r'C:\Users\Dell\Downloads\E-scrapper'

# ── helpers ────────────────────────────────────────────────────────────────────
def clean(text):
    text = text.replace('\u2013', '')   # en-dash (–)
    text = text.replace('\u2014', '')   # em-dash (—)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()

def esc(t):
    return t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def parse_headline(raw):
    lines = [l.strip() for l in raw.split('\n') if l.strip()]
    main  = lines[0] if lines else ''
    decks, intro = [], ''
    for ln in lines[1:]:
        (intro := ln) if len(ln) > 110 else decks.append(ln)
    return main, decks, intro

def render_body(raw_body):
    paras = [p.replace('\n', ' ').strip() for p in raw_body.split('\n\n') if p.strip()]
    out, first = [], True
    for p in paras:
        c = clean(p)
        if not c: continue
        if first:
            out.append(f'<p class="dateline">{esc(c)}</p>'); first = False; continue
        if len(c) < 64 and not c.endswith('.') and not c.endswith(':-'):
            out.append(f'<h3 class="subhd">{esc(c)}</h3>')
        else:
            out.append(f'<p>{esc(c)}</p>')
    return '\n        '.join(out)

# ── editions list ──────────────────────────────────────────────────────────────
# Base list: (name, fallback_code)
# fallback_code is used only if editions_map.json doesn't have a real EID.
# Numeric codes (like "77") are real EIDs that work immediately.
_BASE_EDITIONS = [
    ("Andhra",                           "247"),
    ("Bengaluru",                        "137"),
    ("Chengalpattu",                     "264"),
    ("Chennai City",                     "77"),
    ("Chidambaram & Virudhachalam",      "254"),
    ("Coimbatore",                       "226"),
    ("Colombo",                          "263"),
    ("Cuddalore",                        "262"),
    ("Dharampuri",                       "261"),
    ("Dindigul",                         "261"),
    ("Dindigul District",                "212"),
    ("Dubai",                            "186"),
    ("Erode",                            "234"),
    ("Erode District",                   "231"),
    ("Hosur",                            "hos"),
    ("Kallakurichi",                     "251"),
    ("Kancheepuram",                     "192"),
    ("Kangeyam, Dharapuram, U.Malai",    "227"),
    ("Karur",                            "270"),
    ("Kerala & Theni",                   "211"),
    ("Kerala Coimbatore",                "233"),
    ("Kerala Nagarcoil",                 "243"),
    ("Krishnagiri",                      "235"),
    ("Kumbakonam & Pattukottai",         "221"),
    ("Kunnatur, Ch.Palli, U.Kuli",       "259"),
    ("Madurai",                          "210"),
    ("Mangalore & Raichur",              "195"),
    ("Mumbai",                           "147"),
    ("Mysore & KGF",                     "196"),
    ("Nagai & Karaikal",                 "219"),
    ("Nagarcoil",                        "246"),
    ("Nagarcoil District",               "244"),
    ("Namakkal",                         "236"),
    ("Nilgiris (Ooty)",                  "224"),
    ("Perambalur & Ariyalur",            "215"),
    ("Pollachi & Mettupalayam",          "225"),
    ("Pondicherry",                      "157"),
    ("Pudukkottai",                      "216"),
    ("Ramnad & Sivagangai",              "207"),
    ("Ranipet & Tirupathur District",    "249"),
    ("Salem City",                       "238"),
    ("Salem District",                   "256"),
    ("Tanjore",                          "222"),
    ("Thoothukudi (Tuticorin)",          "239"),
    ("Tirunelveli",                      "240"),
    ("Tirunelveli District",             "255"),
    ("Tirupur",                          "230"),
    ("Tirupur District",                 "257"),
    ("Tiruvallur",                       "255"),
    ("Tiruvannamalai",                   "248"),
    ("Tiruvarur",                        "220"),
    ("Trichy",                           "218"),
    ("Vellore",                          "250"),
    ("Villupuram",                       "252"),
    ("Villupuram & Cuddalore",           "252"),
    ("Virudhunagar",                     "208"),
]

# Load discovered EIDs from editions_map.json (produced by discover_editions.py)
_eid_map_path = os.path.join(BASE, 'editions_map.json')
_discovered_eids: dict = {}
if os.path.isfile(_eid_map_path):
    try:
        with open(_eid_map_path, encoding='utf-8') as _f:
            _discovered_eids = json.load(_f)
        print(f"Loaded {len(_discovered_eids)} EIDs from editions_map.json")
    except Exception as _e:
        print(f"Warning: could not load editions_map.json — {_e}")

def _resolve_eid(name: str, fallback: str) -> str:
    """Return the best EID for this edition name."""
    # Direct match in discovered map
    if name in _discovered_eids:
        return _discovered_eids[name]
    # Fallback code — if it's numeric it's a real EID, otherwise just a placeholder
    return fallback

# Final EDITIONS list with best available EIDs
EDITIONS = [(name, _resolve_eid(name, fb)) for name, fb in _BASE_EDITIONS]

known_count = sum(1 for _, e in EDITIONS if e.lstrip('-').isdigit())
print(f"Editions with known numeric EIDs: {known_count}/{len(EDITIONS)}")

def editions_html():
    parts = []
    for name, eid in EDITIONS:
        sel = ' selected' if name == 'Madurai' else ''
        chk = '<span class="chk">&#10003;</span>' if name == 'Madurai' else ''
        parts.append(
            f'<div class="ed-item{sel}" onclick="selectEd(\'{esc(name)}\',\'{eid}\')" '
            f'data-n="{name.lower()}">{esc(name)}{chk}</div>'
        )
    return '\n          '.join(parts)

def article_html(art, idx, date):
    main, decks, intro = parse_headline(art['headline'])
    body   = render_body(art['body'])
    cols   = 'c3' if idx == 0 else 'c2'
    sid    = art.get('story_id','')
    dkhtml = (''.join(f'<li>{esc(d)}</li>' for d in decks)) if decks else ''
    intro_h = f'<p class="intro">{esc(intro)}</p>' if intro else ''
    return f'''\
  <article class="art" id="s{sid}">
    <div class="hl-block">
      <h1 class="mhl">{esc(main)}</h1>
      {"<ul class='deck'>"+dkhtml+"</ul>" if dkhtml else ""}
      {intro_h}
    </div>
    <div class="art-img" data-sid="{sid}">
      <div class="img-ph">
        <svg viewBox="0 0 120 70" xmlns="http://www.w3.org/2000/svg">
          <rect width="120" height="70" fill="#ececec"/>
          <circle cx="35" cy="25" r="12" fill="#c9c9c9"/>
          <polygon points="0,55 30,35 55,50 80,25 120,45 120,70 0,70" fill="#d8d8d8"/>
        </svg>
        <p>செய்தி படம் &nbsp;·&nbsp; Story {sid}</p>
      </div>
    </div>
    <div class="body {cols}">
      {body}
    </div>
  </article>'''

# ── load data ──────────────────────────────────────────────────────────────────
jpath = os.path.join(BASE, 'scraped_data (1).json')
with open(jpath, encoding='utf-8') as f:
    data = json.load(f)

date = data.get('date', '03/03/2026')
arts_html = '\n'.join(article_html(a, i, date) for i, a in enumerate(data['articles']))

# ── CSS ────────────────────────────────────────────────────────────────────────
CSS = """
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Noto Sans Tamil', 'Nirmala UI', 'Latha', Arial, sans-serif;
    background: #e8e8e8;
    color: #111;
    font-size: 13pt;
  }

  /* ── LOADING OVERLAY ── */
  #loading-overlay {
    display: none; position: fixed; inset: 0; z-index: 9000;
    background: rgba(255,255,255,.88);
    flex-direction: column; align-items: center; justify-content: center;
  }
  #loading-overlay.active { display: flex; }
  .spinner {
    width: 52px; height: 52px;
    border: 5px solid #eee;
    border-top-color: #c00;
    border-radius: 50%;
    animation: spin .8s linear infinite;
  }
  #loading-msg {
    margin-top: 18px; font-size: 13pt; color: #333; text-align: center; max-width: 320px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── TOP NAV BAR ── */
  .topnav {
    position: sticky; top: 0; z-index: 200;
    background: #fff;
    border-bottom: 2px solid #c00;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 16px;
    height: 42px;
    font-size: 10pt;
    box-shadow: 0 2px 6px rgba(0,0,0,.15);
  }
  .nav-left { display: flex; align-items: center; gap: 4px; }
  .nav-sep  { color: #bbb; margin: 0 4px; }
  .nav-item { display: flex; align-items: center; gap: 4px; color: #333; white-space: nowrap; }
  .nav-item svg { width:14px; height:14px; fill:#888; }
  .nav-btn {
    background: none; border: none; cursor: pointer;
    display: flex; align-items: center; gap: 4px;
    font-size: 10pt; font-family: inherit; color: #111; font-weight: 700;
    padding: 6px 8px; border-radius: 4px;
  }
  .nav-btn:hover { background: #f2f2f2; }
  .nav-center { font-size: 13pt; font-weight: 900; color: #c00; }
  .nav-right  { display: flex; align-items: center; gap: 12px; font-size: 10pt; color:#555; }
  .nav-right input {
    border: 1px solid #ddd; border-radius: 20px;
    padding: 4px 12px; font-size: 9.5pt; width: 150px; outline: none;
  }

  /* ── TOOLBAR ── */
  .toolbar {
    background: #fafafa; border-bottom: 1px solid #ddd;
    display: flex; gap: 24px; justify-content: center;
    padding: 6px 16px; font-size: 9.5pt; color: #555;
  }
  .tool-btn {
    display: flex; flex-direction: column; align-items: center; gap: 2px;
    cursor: pointer; padding: 4px 8px; border-radius: 4px;
  }
  .tool-btn:hover { background: #eee; }
  .tool-btn svg { width:18px; height:18px; }
  .tool-btn.discover { color: #2a7d2a; font-weight: 700; }
  .tool-btn.discover svg { fill: #2a7d2a; }
  .tool-btn.pdf-dl { color: #c00; font-weight: 700; }
  .tool-btn.pdf-dl svg { fill: #c00; }
  .tool-btn.pdf-dl.disabled { opacity: 0.35; cursor: not-allowed !important; pointer-events: none; }

  /* ── EDITION MODAL ── */
  .modal-overlay {
    display: none; position: fixed; inset: 0; z-index: 999;
    background: rgba(0,0,0,.55); align-items: center; justify-content: center;
  }
  .modal-overlay.open { display: flex; }
  .modal-box {
    background: #fff; border-radius: 4px; width: 780px; max-width: 96vw;
    max-height: 88vh; overflow: hidden;
    display: flex; flex-direction: column;
    box-shadow: 0 8px 32px rgba(0,0,0,.35);
  }
  .modal-hdr {
    background: #222; color: #fff; padding: 12px 18px;
    display: flex; justify-content: space-between; align-items: center;
    font-size: 13pt; font-weight: 700; flex-shrink: 0;
  }
  .modal-close {
    background: none; border: 1px solid #888; color: #fff; width: 26px; height: 26px;
    border-radius: 2px; cursor: pointer; font-size: 14pt; line-height: 1;
    display: flex; align-items: center; justify-content: center;
  }
  .modal-search {
    flex-shrink: 0; padding: 10px 14px; border-bottom: 1px solid #eee;
  }
  .modal-search input {
    width: 100%; border: 1px solid #ccc; border-radius: 4px;
    padding: 7px 12px; font-size: 10.5pt; outline: none;
  }
  .modal-search input:focus { border-color: #c00; }
  .modal-body {
    overflow-y: auto; padding: 10px 0 14px;
    display: grid; grid-template-columns: repeat(3, 1fr);
  }
  .ed-item {
    padding: 9px 18px; font-size: 10.5pt; cursor: pointer;
    display: flex; justify-content: space-between; align-items: center;
    border-bottom: 1px solid #f2f2f2; color: #222;
  }
  .ed-item:hover { background: #f8f8f8; }
  .ed-item.selected { color: #2a7d2a; font-weight: 700; }
  .ed-item.hidden   { display: none; }
  .ed-item.no-eid   { color: #aaa; }
  .ed-item.no-eid::after { content: ' *'; font-size: 8pt; color: #c00; }
  .chk { color: #2a7d2a; font-size: 13pt; margin-left: 6px; }
  .ed-none { grid-column: 1/-1; text-align: center; padding: 20px; color: #888; display: none; }
  .modal-footer {
    flex-shrink: 0; padding: 8px 14px; border-top: 1px solid #eee;
    font-size: 9pt; color: #888; text-align: center;
  }
  .modal-footer .red { color: #c00; font-weight: 700; }

  /* ── VIEWER LAYOUT (sidebar + content) ── */
  .viewer-layout {
    display: flex;
    align-items: flex-start;
    max-width: 1300px;
    margin: 0 auto;
  }

  /* ── PAGE SIDEBAR ── */
  .page-sidebar {
    width: 128px;
    min-width: 128px;
    background: #2a2a2a;
    overflow-y: auto;
    max-height: calc(100vh - 86px);
    position: sticky;
    top: 86px;
    display: none;  /* hidden until pages data arrives */
  }
  .page-sidebar.visible { display: block; }

  .thumb-item {
    padding: 7px 6px 5px;
    cursor: pointer;
    border-bottom: 1px solid #3a3a3a;
    border-left: 3px solid transparent;
    transition: background .15s;
  }
  .thumb-item:hover { background: #383838; }
  .thumb-item.active { background: #3d3d3d; border-left-color: #e67a00; }

  .thumb-item img {
    width: 100%;
    height: 90px;
    object-fit: cover;
    display: block;
    background: #555;
    border-radius: 2px;
  }
  .thumb-placeholder {
    width: 100%;
    height: 90px;
    background: #444;
    border-radius: 2px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #888;
    font-size: 8pt;
  }
  .thumb-label {
    color: #bbb;
    font-size: 8pt;
    text-align: center;
    margin-top: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding: 0 2px;
  }

  /* ── CONTENT COLUMN (holds the paper) ── */
  .content-col { flex: 1; min-width: 0; }

  /* ── PAGE NAV DROPDOWN (in topnav) ── */
  .nav-page-wrap { position: relative; }
  .nav-page-dropdown {
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    background: #fff;
    border: 1px solid #ddd;
    min-width: 175px;
    max-height: 420px;
    overflow-y: auto;
    z-index: 600;
    box-shadow: 0 4px 14px rgba(0,0,0,.18);
  }
  .nav-page-dropdown.open { display: block; }
  .nav-pg-item {
    padding: 8px 16px;
    font-size: 10.5pt;
    cursor: pointer;
    color: #222;
    border-bottom: 1px solid #f2f2f2;
  }
  .nav-pg-item:hover { background: #f5f5f5; }
  .nav-pg-item.active { background: #555; color: #fff; font-weight: 700; }

  /* ── PAPER WRAPPER ── */
  .paper { margin: 20px; background: #fff; padding: 28px 36px 48px; }

  /* ── NAMEPLATE ── */
  .nameplate {
    border-top: 5px solid #c00; border-bottom: 2.5px solid #c00;
    padding: 10px 0 8px; display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 6px;
  }
  .np-title { font-size: 40pt; font-weight: 900; color: #c00; letter-spacing: -1px; line-height:1; }
  .np-meta  { text-align: right; font-size: 9.5pt; color: #444; line-height: 1.7; }
  .np-meta strong { font-size: 11pt; color: #111; }
  .ed-bar {
    background: #c00; color: #fff; font-size: 9pt; font-weight:700;
    padding: 3px 10px; margin-bottom: 22px; letter-spacing:.5px;
    display: flex; justify-content: space-between;
  }

  /* ── ARTICLE ── */
  .art { border-bottom: 2px solid #bbb; padding-bottom: 28px; margin-bottom: 30px; }
  .art:last-child { border-bottom: none; padding-bottom: 0; margin-bottom: 0; }

  /* headline block */
  .hl-block {
    border-bottom: 1.5px solid #888; padding-bottom: 12px; margin-bottom: 14px;
  }
  .mhl {
    font-size: 24pt; font-weight: 900; line-height: 1.18; color: #111; margin-bottom: 8px;
  }
  .deck {
    list-style: none; border-left: 4px solid #c00; padding-left: 12px; margin: 8px 0 0;
  }
  .deck li { font-size: 13pt; font-weight: 700; line-height: 1.45; color: #222; }
  .deck li+li { margin-top: 3px; }
  .intro {
    font-size: 11.5pt; font-weight: 600; color: #333; line-height: 1.65;
    margin-top: 10px; padding: 8px 12px; border-left: 3px solid #ddd; background: #fafafa;
  }

  /* image placeholder */
  .art-img { margin: 12px 0; }
  .img-ph {
    background: #ececec; border: 1px solid #ddd; border-radius: 3px;
    overflow: hidden; display: flex; flex-direction: column; align-items: center;
    max-width: 400px;
  }
  .img-ph svg { width: 100%; display: block; }
  .img-ph p {
    font-size: 9pt; color: #888; padding: 5px 10px; background: #f6f6f6;
    width: 100%; text-align: center; border-top: 1px solid #e0e0e0;
  }

  /* body columns */
  .body {
    text-align: justify; font-size: 11.5pt; line-height: 1.78;
    column-gap: 22px; column-rule: 1px solid #ddd;
    hyphens: none; -webkit-hyphens: none; word-break: break-word;
  }
  .c3 { column-count: 3; }
  .c2 { column-count: 2; }
  .body p   { margin-bottom: 9px; orphans:3; widows:3; }
  .dateline { font-size: 10.5pt; font-weight: 700; color: #555; margin-bottom: 10px; }
  .subhd    { font-size: 11.5pt; font-weight: 800; color: #c00; margin: 14px 0 5px; break-after: avoid; }

  /* no-articles message */
  .no-articles {
    padding: 48px 20px; text-align: center; color: #888; font-size: 14pt;
  }

  /* ── PRINT ── */
  @page { size: A4; margin: 14mm 12mm; }
  @media print {
    body       { background: #fff; }
    .topnav, .toolbar, .modal-overlay, #loading-overlay { display: none !important; }
    .paper     { margin:0; padding:0; box-shadow:none; }
    .c3        { column-count: 3; }
    .c2        { column-count: 2; }
    .art       { page-break-inside: avoid; }
    .np-title  { font-size: 30pt; }
    .mhl       { font-size: 18pt; }
    .body      { font-size: 10pt; }
  }
"""

# ── JS ─────────────────────────────────────────────────────────────────────────
JS = r"""
  // ── Config ──────────────────────────────────────────────────────────────────
  // When served via FastAPI (/viewer), use same-origin relative URLs.
  // If opened directly as file://, fall back to localhost:8000.
  const API_BASE = location.protocol === 'file:' ? 'http://localhost:8000' : '';
  // Compute today's date dynamically so the viewer always fetches the current edition
  (function() {
    const _d = new Date();
    window.EDATE = String(_d.getDate()).padStart(2,'0') + '/' +
                   String(_d.getMonth()+1).padStart(2,'0') + '/' +
                   _d.getFullYear();
  })();
  const EDATE = window.EDATE;

  // EID map: populated by discoverEditions(), also pre-seeded with known EIDs.
  // Key = lowercase edition name, value = numeric EID string.
  const eidMap = {
    'andhra': '247',
    'bengaluru': '137',
    'chengalpattu': '264',
    'chennai city': '77',
    'chidambaram & virudhachalam': '254',
    'coimbatore': '226',
    'colombo': '263',
    'cuddalore': '262',
    'dharampuri': '261',
    'dindigul': '261',
    'dindigul district': '212',
    'dubai': '186',
    'erode': '234',
    'erode district': '231',
    'kallakurichi': '251',
    'kancheepuram': '192',
    'kangeyam, dharapuram, u.malai': '227',
    'karur': '270',
    'kerala & theni': '211',
    'kerala coimbatore': '233',
    'kerala nagarcoil': '243',
    'krishnagiri': '235',
    'kumbakonam & pattukottai': '221',
    'kunnatur, ch.palli, u.kuli': '259',
    'madurai': '210',
    'mangalore & raichur': '195',
    'mumbai': '147',
    'mysore & kgf': '196',
    'nagai & karaikal': '219',
    'nagarcoil': '246',
    'nagarcoil district': '244',
    'namakkal': '236',
    'nilgiris (ooty)': '224',
    'perambalur & ariyalur': '215',
    'pollachi & mettupalayam': '225',
    'pondicherry': '157',
    'pudukkottai': '216',
    'ramnad & sivagangai': '207',
    'ranipet & tirupathur district': '249',
    'salem city': '238',
    'salem district': '256',
    'tanjore': '222',
    'thoothukudi (tuticorin)': '239',
    'tirunelveli': '240',
    'tirunelveli district': '255',
    'tirupur': '230',
    'tirupur district': '257',
    'tiruvallur': '255',
    'tiruvannamalai': '248',
    'tiruvarur': '220',
    'trichy': '218',
    'vellore': '250',
    'villupuram': '252',
    'villupuram & cuddalore': '252',
    'virudhunagar': '208',
  };

  // ── Utility ─────────────────────────────────────────────────────────────────
  function cleanText(t) {
    return (t || '')
      .replace(/\u2013/g, '')
      .replace(/\u2014/g, '')
      .replace(/[ \t]{2,}/g, ' ')
      .trim();
  }

  function escHtml(t) {
    return (t || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Loading overlay ──────────────────────────────────────────────────────────
  function showLoading(msg) {
    document.getElementById('loading-msg').textContent = msg || 'Loading...';
    document.getElementById('loading-overlay').classList.add('active');
  }
  function hideLoading() {
    document.getElementById('loading-overlay').classList.remove('active');
  }

  // ── Toast notification ───────────────────────────────────────────────────────
  function showToast(msg, isError) {
    const el = document.getElementById('ed-notice');
    el.textContent = msg;
    el.style.background = isError ? '#900' : '#333';
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 5000);
  }

  // ── State: currently loaded edition + pages ──────────────────────────────────
  let _currentEid = '';
  let _currentEditionName = 'Madurai';
  let _currentPages = [];
  let _currentPageIdx = 0;

  // ── Page dropdown toggle ──────────────────────────────────────────────────────
  function togglePageDropdown() {
    const dd = document.getElementById('nav-page-dropdown');
    if (dd) dd.classList.toggle('open');
  }
  // Close page dropdown when clicking outside
  document.addEventListener('click', function(e) {
    const wrap = document.getElementById('nav-page-wrap');
    if (wrap && !wrap.contains(e.target)) {
      const dd = document.getElementById('nav-page-dropdown');
      if (dd) dd.classList.remove('open');
    }
  });

  // ── Switch to a specific newspaper page ──────────────────────────────────────
  function selectPage(idx) {
    if (idx < 0 || idx >= _currentPages.length) return;
    _currentPageIdx = idx;
    const pg = _currentPages[idx];

    // Update topnav label + close dropdown
    const lbl = document.getElementById('cur-page-label');
    if (lbl) lbl.textContent = pg.label || ('page ' + (idx + 1));
    const dd = document.getElementById('nav-page-dropdown');
    if (dd) dd.classList.remove('open');

    // Update sidebar active state
    document.querySelectorAll('.thumb-item').forEach((el, i) => {
      el.classList.toggle('active', i === idx);
      if (i === idx) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });

    // Update dropdown active state
    document.querySelectorAll('.nav-pg-item').forEach((el, i) => {
      el.classList.toggle('active', i === idx);
    });

    // Replace article section with this page's articles
    const paper = document.querySelector('.paper');
    if (!paper) return;
    paper.querySelectorAll('.art, .no-articles').forEach(el => el.remove());

    const articles = pg.articles || [];
    if (articles.length === 0) {
      const msg = document.createElement('div');
      msg.className = 'no-articles';
      msg.textContent = 'இந்த பக்கத்தில் செய்திகள் கிடைக்கவில்லை.';
      paper.appendChild(msg);
    } else {
      articles.forEach((art, i) => {
        const tmp = document.createElement('div');
        tmp.innerHTML = renderArticleHtml(art, i);
        paper.appendChild(tmp.firstElementChild);
      });
    }
    paper.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ── Build left sidebar from pages data ───────────────────────────────────────
  function renderPageSidebar(pages) {
    const sidebar = document.getElementById('page-sidebar');
    if (!sidebar) return;
    sidebar.innerHTML = '';
    sidebar.classList.toggle('visible', pages.length > 0);
    pages.forEach((pg, idx) => {
      const item = document.createElement('div');
      item.className = 'thumb-item' + (idx === 0 ? ' active' : '');
      item.onclick = () => selectPage(idx);
      if (pg.screenshot_b64) {
        const img = document.createElement('img');
        img.src = 'data:image/jpeg;base64,' + pg.screenshot_b64;
        img.alt = pg.label || ('page ' + (idx + 1));
        item.appendChild(img);
      } else {
        const ph = document.createElement('div');
        ph.className = 'thumb-placeholder';
        ph.textContent = pg.label || ('p' + (idx + 1));
        item.appendChild(ph);
      }
      const lbl = document.createElement('div');
      lbl.className = 'thumb-label';
      lbl.textContent = pg.label || ('page ' + (idx + 1));
      item.appendChild(lbl);
      sidebar.appendChild(item);
    });
  }

  // ── Build page dropdown from pages data ──────────────────────────────────────
  function renderPageDropdown(pages) {
    const dd = document.getElementById('nav-page-dropdown');
    if (!dd) return;
    dd.innerHTML = '';
    pages.forEach((pg, idx) => {
      const item = document.createElement('div');
      item.className = 'nav-pg-item' + (idx === 0 ? ' active' : '');
      item.textContent = pg.label || ('page ' + (idx + 1));
      item.onclick = () => selectPage(idx);
      dd.appendChild(item);
    });
  }

  // ── Download PDF ─────────────────────────────────────────────────────────────
  async function downloadPdf() {
    const btn = document.getElementById('pdf-btn');
    if (btn && btn.classList.contains('disabled')) return;
    showLoading(_currentEditionName + ' PDF தயாரிக்கிறது... (1–3 நிமிடங்கள் ஆகலாம்)');
    try {
      const resp = await fetch(API_BASE + '/api/scrape/edition-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ eid: _currentEid, edition_name: _currentEditionName, date: EDATE }),
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({ detail: 'HTTP ' + resp.status }));
        throw new Error(errData.detail || 'HTTP ' + resp.status);
      }
      const blob = await resp.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      const dateStr = EDATE.replace(/\//g, '-');
      a.download = 'dailythanthi_' + dateStr + '_' + _currentEditionName.replace(/\s+/g, '_') + '.pdf';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      hideLoading();
      showToast(_currentEditionName + ' PDF பதிவிறக்கம் தொடங்கியது!');
    } catch (err) {
      hideLoading();
      showToast('PDF பிழை: ' + err.message, true);
    }
  }

  // ── Modal ────────────────────────────────────────────────────────────────────
  function openModal()  { document.getElementById('ed-modal').classList.add('open'); }
  function closeModal() { document.getElementById('ed-modal').classList.remove('open'); }

  document.getElementById('ed-modal').addEventListener('click', function(e){
    if (e.target === this) closeModal();
  });

  // Edition search filter
  document.getElementById('ed-search').addEventListener('input', function(){
    const q = this.value.toLowerCase().trim();
    let visible = 0;
    document.querySelectorAll('.ed-item').forEach(el => {
      const match = el.dataset.n.includes(q);
      el.classList.toggle('hidden', !match);
      if (match) visible++;
    });
    document.getElementById('ed-none').style.display = visible ? 'none' : 'block';
  });

  // ── Article rendering ────────────────────────────────────────────────────────
  function parseHeadline(raw) {
    const lines = (raw || '').split('\n').map(l => l.trim()).filter(Boolean);
    const main  = lines[0] || '';
    const decks = [], introArr = [];
    lines.slice(1).forEach(ln => {
      if (ln.length > 110) introArr.push(ln);
      else decks.push(ln);
    });
    return { main, decks, intro: introArr.join(' ') };
  }

  function renderBody(rawBody) {
    const paras = (rawBody || '')
      .split('\n\n')
      .map(p => cleanText(p.replace(/\n/g, ' ')))
      .filter(Boolean);
    let first = true;
    return paras.map(c => {
      if (!c) return '';
      if (first) {
        first = false;
        return `<p class="dateline">${escHtml(c)}</p>`;
      }
      if (c.length < 64 && !c.endsWith('.') && !c.endsWith(':-')) {
        return `<h3 class="subhd">${escHtml(c)}</h3>`;
      }
      return `<p>${escHtml(c)}</p>`;
    }).filter(Boolean).join('\n');
  }

  function renderArticleHtml(art, idx) {
    const headline = cleanText(art.headline || '');
    const body     = art.body || '';
    const sid      = art.story_id || '';
    const cols     = idx === 0 ? 'c3' : 'c2';
    const { main, decks, intro } = parseHeadline(headline);

    const deckHtml  = decks.length
      ? `<ul class="deck">${decks.map(d => `<li>${escHtml(d)}</li>`).join('')}</ul>`
      : '';
    const introHtml = intro ? `<p class="intro">${escHtml(intro)}</p>` : '';
    const bodyHtml  = renderBody(body);

    return `
    <article class="art" id="s${escHtml(sid)}">
      <div class="hl-block">
        <h1 class="mhl">${escHtml(main)}</h1>
        ${deckHtml}
        ${introHtml}
      </div>
      <div class="art-img" data-sid="${escHtml(sid)}">
        <div class="img-ph">
          <svg viewBox="0 0 120 70" xmlns="http://www.w3.org/2000/svg">
            <rect width="120" height="70" fill="#ececec"/>
            <circle cx="35" cy="25" r="12" fill="#c9c9c9"/>
            <polygon points="0,55 30,35 55,50 80,25 120,45 120,70 0,70" fill="#d8d8d8"/>
          </svg>
          <p>செய்தி படம் &nbsp;·&nbsp; Story ${escHtml(sid)}</p>
        </div>
      </div>
      <div class="body ${cols}">
        ${bodyHtml}
      </div>
    </article>`;
  }

  function renderAllArticles(articles, editionName, date, pages) {
    const paper = document.querySelector('.paper');
    if (!paper) return;

    // Update edition bar
    const edBar = paper.querySelector('.ed-bar');
    if (edBar) {
      edBar.innerHTML =
        `<span>இன்றைய சிறப்பு செய்திகள் — ${escHtml(editionName)} பதிப்பு</span>` +
        `<span>${escHtml(date)}</span>`;
    }

    // Update nameplate meta
    const npMeta = paper.querySelector('.np-meta');
    if (npMeta) {
      npMeta.innerHTML =
        `<strong>${escHtml(date)} | Daily Thanthi</strong><br/>` +
        `${escHtml(editionName)} Edition &nbsp;|&nbsp; www.dailythanthi.com`;
    }

    // Remove old articles
    paper.querySelectorAll('.art, .no-articles').forEach(el => el.remove());

    if (pages && pages.length > 0) {
      // Page-aware mode: wire up sidebar + dropdown, show page 1 articles
      _currentPages = pages;
      _currentPageIdx = 0;
      renderPageSidebar(pages);
      renderPageDropdown(pages);
      const firstLabel = pages[0].label || 'news 1';
      const lbl = document.getElementById('cur-page-label');
      if (lbl) lbl.textContent = firstLabel;
      // Render page 1 articles
      const pg1Arts = pages[0].articles || [];
      if (pg1Arts.length === 0) {
        const msg = document.createElement('div');
        msg.className = 'no-articles';
        msg.textContent = 'இந்த பக்கத்தில் செய்திகள் கிடைக்கவில்லை.';
        paper.appendChild(msg);
      } else {
        pg1Arts.forEach((art, idx) => {
          const tmp = document.createElement('div');
          tmp.innerHTML = renderArticleHtml(art, idx);
          paper.appendChild(tmp.firstElementChild);
        });
      }
    } else {
      // Flat mode (no pages): render all articles
      if (!articles || articles.length === 0) {
        const msg = document.createElement('div');
        msg.className = 'no-articles';
        msg.textContent = 'இந்த பதிப்பிற்கான செய்திகள் கிடைக்கவில்லை. (No articles found for this edition.)';
        paper.appendChild(msg);
        return;
      }
      articles.forEach((art, idx) => {
        const tmp = document.createElement('div');
        tmp.innerHTML = renderArticleHtml(art, idx);
        paper.appendChild(tmp.firstElementChild);
      });
    }

    paper.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ── Discover editions from backend ──────────────────────────────────────────
  async function discoverEditions(showFeedback) {
    if (showFeedback) showLoading('Edition IDs கண்டுபிடிக்கிறது...');
    try {
      const resp = await fetch(API_BASE + '/api/scrape/discover-editions', { method: 'POST' });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      const editions = data.editions || [];
      editions.forEach(e => {
        if (e.name && e.eid) {
          eidMap[e.name]               = e.eid;
          eidMap[e.name.toLowerCase()] = e.eid;
        }
      });
      // Mark edition items that now have a resolved EID
      document.querySelectorAll('.ed-item').forEach(el => {
        const name = el.dataset.n;
        if (eidMap[name]) el.classList.remove('no-eid');
      });
      if (showFeedback) {
        hideLoading();
        showToast(`${editions.length} editions கண்டுபிடிக்கப்பட்டன!`);
      }
      console.log('[DT] Discovered editions:', Object.keys(eidMap));
    } catch (err) {
      if (showFeedback) {
        hideLoading();
        showToast('Discovery பிழை: ' + err.message + '. Backend இயங்குகிறதா?', true);
      }
      console.warn('[DT] Edition discovery failed:', err);
    }
  }

  // Mark editions without known numeric EIDs on initial load
  function markUnknownEids() {
    document.querySelectorAll('.ed-item').forEach(el => {
      const eid = el.getAttribute('onclick').match(/'([^']+)'\s*\)$/)?.[1] || '';
      if (!/^\d+$/.test(eid) && !eidMap[el.dataset.n]) {
        el.classList.add('no-eid');
      }
    });
  }

  // ── Select edition ───────────────────────────────────────────────────────────
  async function selectEd(name, eid) {
    // Update UI state immediately
    document.getElementById('cur-edition').textContent = name;
    document.querySelectorAll('.ed-item').forEach(el => {
      const isThis = el.dataset.n === name.toLowerCase();
      el.classList.toggle('selected', isThis);
      const chk = el.querySelector('.chk');
      if (isThis && !chk) {
        const s = document.createElement('span');
        s.className = 'chk'; s.innerHTML = '&#10003;';
        el.appendChild(s);
      } else if (!isThis && chk) {
        chk.remove();
      }
    });
    closeModal();

    // Resolve to a numeric EID if we have one cached; otherwise pass "" so the
    // backend uses name-based navigation (logs in → opens edition selector → finds by name).
    let resolvedEid = eid;
    if (!/^\d+$/.test(eid)) {
      resolvedEid = eidMap[name] || eidMap[name.toLowerCase()] || '';
      if (!resolvedEid || !/^\d+$/.test(resolvedEid)) {
        resolvedEid = '';  // backend will navigate by edition_name
      }
    }

    // Fetch articles from backend
    showLoading(name + ' பதிப்பு செய்திகளை பதிவிறக்குகிறது... (இது 1–2 நிமிடம் ஆகலாம்)');
    try {
      const resp = await fetch(API_BASE + '/api/scrape/edition-articles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ eid: resolvedEid, edition_name: name, date: EDATE }),
      });

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({ detail: 'HTTP ' + resp.status }));
        throw new Error(errData.detail || 'HTTP ' + resp.status);
      }

      const data = await resp.json();
      hideLoading();
      renderAllArticles(data.articles, name, data.date || EDATE, data.pages || []);
      // Track state and enable PDF download button
      _currentEid = resolvedEid;
      _currentEditionName = name;
      const pdfBtn = document.getElementById('pdf-btn');
      if (pdfBtn) pdfBtn.classList.remove('disabled');
      const pgCount  = (data.pages  || []).length;
      const artCount = (data.articles || []).length;
      const msg = pgCount > 0
        ? name + ' பதிப்பு — ' + pgCount + ' பக்கங்கள், ' + artCount + ' செய்திகள்'
        : name + ' பதிப்பு — ' + artCount + ' செய்திகள் கிடைத்தன';
      showToast(msg);
    } catch (err) {
      hideLoading();
      showToast('பிழை: ' + err.message, true);
    }
  }

  // ── Init ────────────────────────────────────────────────────────────────────
  markUnknownEids();
  // Auto-discover silently on page load (won't show any UI if backend is down)
  discoverEditions(false);
"""

# ── full HTML ──────────────────────────────────────────────────────────────────
html = f'''<!DOCTYPE html>
<html lang="ta">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>தினத்தந்தி &mdash; {date}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Tamil:wght@400;600;700;900&display=swap" rel="stylesheet" />
  <style>
{CSS}
  </style>
</head>
<body>

<!-- ░░ LOADING OVERLAY ░░ -->
<div id="loading-overlay">
  <div class="spinner"></div>
  <p id="loading-msg">Loading...</p>
</div>

<!-- ░░ TOP NAV ░░ -->
<nav class="topnav">
  <div class="nav-left">
    <span class="nav-item">
      <svg viewBox="0 0 24 24"><path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"/></svg>
      Home
    </span>
    <span class="nav-sep">|</span>
    <span class="nav-item">
      <svg viewBox="0 0 24 24"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.1 0-2 .9-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11z"/></svg>
      {date}
    </span>
    <span class="nav-sep">|</span>
    <button class="nav-btn" onclick="openModal()">
      <svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:#888"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
      <span id="cur-edition">Madurai</span>
      <svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:#555"><path d="M7 10l5 5 5-5z"/></svg>
    </button>
    <span class="nav-sep">|</span>
    <div class="nav-page-wrap" id="nav-page-wrap">
      <button class="nav-btn" onclick="togglePageDropdown()" id="nav-page-btn">
        <span id="cur-page-label">news 1</span>
        <svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:#555"><path d="M7 10l5 5 5-5z"/></svg>
      </button>
      <div class="nav-page-dropdown" id="nav-page-dropdown"></div>
    </div>
  </div>
  <div class="nav-center">dailythanthi.com</div>
  <div class="nav-right">
    <input type="text" placeholder="Search..." />
    <span>&#128269;</span>
  </div>
</nav>

<!-- ░░ TOOLBAR ░░ -->
<div class="toolbar">
  <div class="tool-btn">
    <svg viewBox="0 0 24 24" fill="#555"><path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"/></svg>
    Text View
  </div>
  <div class="tool-btn">
    <svg viewBox="0 0 24 24" fill="#555"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
    Save as favourite
  </div>
  <div class="tool-btn">
    <svg viewBox="0 0 24 24" fill="#555"><path d="M9 4v3H5v13h14V7h-4V4H9zm0 2h6v1H9V6zm-2 3h10v9H7V9zm4 1v6h2v-6h-2zm-3 0v2h2v-2H8zm6 0v2h2v-2h-2zM8 13v2h2v-2H8zm6 0v2h2h-2z"/></svg>
    Font Size
  </div>
  <div class="tool-btn discover" onclick="discoverEditions(true)" title="Discover EIDs for all editions (requires backend + login)">
    <svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm1 17h-2v-2h2zm2.07-7.75l-.9.92C13.45 13.9 13 14.5 13 16h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H8a4 4 0 0 1 8 0 3.17 3.17 0 0 1-.93 2.25z"/></svg>
    Discover Editions
  </div>
  <div class="tool-btn pdf-dl disabled" id="pdf-btn" onclick="downloadPdf()" title="Download all articles as PDF (select an edition first)">
    <svg viewBox="0 0 24 24"><path d="M20 2H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-8.5 7.5c0 .83-.67 1.5-1.5 1.5H9v2H7.5V7H10c.83 0 1.5.67 1.5 1.5v1zm5 2c0 .83-.67 1.5-1.5 1.5h-2.5V7H15c.83 0 1.5.67 1.5 1.5v3zm4-3H19v1h1.5V11H19v2h-1.5V7h3v1.5zM9 9.5h1v-1H9v1zM4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm10 5.5h1v-3h-1v3z"/></svg>
    Download PDF
  </div>
  <div class="tool-btn">
    <svg viewBox="0 0 24 24" fill="#555"><path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/></svg>
    Write To Editor
  </div>
</div>

<!-- ░░ EDITION MODAL ░░ -->
<div class="modal-overlay" id="ed-modal">
  <div class="modal-box">
    <div class="modal-hdr">
      <span>Select Edition</span>
      <button class="modal-close" onclick="closeModal()">&#x2715;</button>
    </div>
    <div class="modal-search">
      <input id="ed-search" type="text" placeholder="&#128269; Search edition..." />
    </div>
    <div class="modal-body">
          {editions_html()}
          <div class="ed-none" id="ed-none">No editions found</div>
    </div>
    <div class="modal-footer">
      எந்த மாவட்டத்தையும் தேர்ந்தெடுக்கலாம் — backend தானாகவே உள்நுழைந்து அந்த edition-ஐ கண்டுபிடிக்கும்.
    </div>
  </div>
</div>

<!-- ░░ EDITION NOTICE / TOAST ░░ -->
<div id="ed-notice" style="display:none;position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
  background:#333;color:#fff;padding:10px 20px;border-radius:6px;font-size:10.5pt;
  z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,.3);text-align:center;max-width:560px;"></div>

<!-- ░░ VIEWER LAYOUT: SIDEBAR + PAPER ░░ -->
<div class="viewer-layout">

<!-- LEFT: page thumbnail sidebar -->
<div class="page-sidebar" id="page-sidebar"></div>

<!-- RIGHT: newspaper paper -->
<div class="content-col">
<div class="paper">
  <div class="nameplate">
    <div class="np-title">தினத்தந்தி</div>
    <div class="np-meta">
      <strong>03 மார்ச் 2026 | திங்கள்</strong><br/>
      Madurai Edition &nbsp;|&nbsp; www.dailythanthi.com
    </div>
  </div>
  <div class="ed-bar">
    <span>இன்றைய சிறப்பு செய்திகள் — மதுரை பதிப்பு</span>
    <span>{date}</span>
  </div>

{arts_html}

</div><!-- /.paper -->
</div><!-- /.content-col -->
</div><!-- /.viewer-layout -->

<script>
{JS}
</script>
</body>
</html>
'''

out = os.path.join(BASE, 'thanthi_layout.html')
with open(out, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Done: {out}")

# Verify no en-dashes remain
with open(out, encoding='utf-8') as f:
    content = f.read()
ndash = content.count('\u2013')
print(f"En-dash count in output: {ndash}  {'OK' if ndash == 0 else 'WARNING: still present'}")
