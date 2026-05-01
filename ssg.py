#!/usr/bin/env python3
"""
Static Site Generator voor cyberstefan.nl
Leest writeups uit SQLite en genereert volledig statische HTML-pagina's.
Alle writeup-content zit in de HTML bij serverresponse — geen JS-fetch nodig.

Gebruik:
    python ssg.py                         # genereer alles
    python ssg.py --dry-run               # toon wat er gegenereerd zou worden
    python ssg.py --writeup sau           # alleen één writeup (slug of ID)
"""

import argparse
import html as _html
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL = "https://cyberstefan.nl"
SITE_NAME = "CyberStefan"
AUTHOR = "CyberStefan"
DB_PATH = Path(__file__).parent / "api" / "writeups.db"
WEB_DIR = Path(__file__).parent / "web"

AFF = {
    "HackTheBox": "https://hacktheboxltd.sjv.io/enroEz",
    "TryHackMe": "https://tryhackme.sjv.io/Gb06VL",
    "NordVPN": "https://go.nordvpn.net/aff_c?offer_id=15&aff_id=146180&url_id=902",
}

IMPACT_VERIFY_1 = "1172fec2-18d2-46f2-a726-ac773ac47674"
IMPACT_VERIFY_2 = "055b58c2-fcab-4781-973d-96e4f1f85fb2"

MONTHS_EN = ["January","February","March","April","May","June",
             "July","August","September","October","November","December"]
MONTHS_NL = ["januari","februari","maart","april","mei","juni",
             "juli","augustus","september","oktober","november","december"]

# ── Helpers ─────────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def format_date(iso: str, locale: str = "en") -> str:
    try:
        dt = datetime.fromisoformat(iso)
        months = MONTHS_NL if locale == "nl" else MONTHS_EN
        return f"{dt.day} {months[dt.month - 1]} {dt.year}"
    except Exception:
        return iso


def strip_markdown(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`]+`", " ", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[(.+?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"[-*|>]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def make_description(text: str, max_len: int = 155) -> str:
    clean = strip_markdown(text)
    if len(clean) <= max_len:
        return clean
    return clean[:max_len - 1].rsplit(" ", 1)[0] + "…"


def md_to_html(md: str) -> str:
    """Zet markdown om naar HTML — zelfde logica als writeup.js renderMarkdown."""
    if not md:
        return "<p>No content.</p>"

    out = _html.escape(md)

    # Fenced code blocks
    out = re.sub(
        r"```\w*\n([\s\S]*?)```",
        lambda m: f"<pre><code>{m.group(1).rstrip()}</code></pre>",
        out,
    )
    # Inline code
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    # Headers (na escaping staat # nog als #)
    out = re.sub(r"^### (.+)$", r"<h3>\1</h3>", out, flags=re.MULTILINE)
    out = re.sub(r"^## (.+)$",  r"<h2>\1</h2>", out, flags=re.MULTILINE)
    out = re.sub(r"^# (.+)$",   r"<h2>\1</h2>", out, flags=re.MULTILINE)
    # Bold / italic
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\*(.+?)\*",     r"<em>\1</em>", out)

    # Unordered lists
    def listify(m: re.Match) -> str:
        items = "".join(
            f"<li>{line[2:]}</li>"
            for line in m.group(0).strip().splitlines()
        )
        return f"<ul>{items}</ul>"
    out = re.sub(r"(^- .+\n?)+", listify, out, flags=re.MULTILINE)

    # Paragraphs — alles wat niet al een block-element is
    blocks = []
    for block in re.split(r"\n\n+", out):
        block = block.strip()
        if not block:
            continue
        if re.match(r"<(h[1-6]|ul|ol|pre|li)", block):
            blocks.append(block)
        else:
            blocks.append(f"<p>{block.replace(chr(10), '<br>')}</p>")
    return "\n".join(blocks)


def load_writeups() -> list[dict]:
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM writeups WHERE status='Completed' ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        w = dict(r)
        w["tags"] = json.loads(w.get("tags") or "[]")
        w["slug"] = slugify(w["machine"])
        result.append(w)
    return result


# ── JSON-LD ──────────────────────────────────────────────────────────────────

def json_ld_article(w: dict) -> str:
    primary = w.get("writeup") or w.get("writeup_nl") or ""
    desc = make_description(primary)
    keywords = w.get("tags", []) + [w["platform"], w["difficulty"], "CTF", "writeup", "ethical hacking"]
    data = {
        "@context": "https://schema.org",
        "@type": "TechArticle",
        "headline": f"{w['machine']} — {w['platform']} CTF Writeup",
        "description": desc,
        "author": {"@type": "Person", "name": AUTHOR, "url": BASE_URL},
        "publisher": {"@type": "Organization", "name": SITE_NAME, "url": BASE_URL},
        "datePublished": w["created_at"],
        "dateModified": w["created_at"],
        "keywords": ", ".join(keywords),
        "articleSection": "CTF Writeup",
        "url": f"{BASE_URL}/writeup/{w['slug']}/",
        "inLanguage": ["en", "nl"],
        "image": f"{BASE_URL}/assets/cyberstefan-icon.png",
    }
    return json.dumps(data, ensure_ascii=False, indent=None)


def json_ld_breadcrumb(w: dict) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{BASE_URL}/"},
            {
                "@type": "ListItem",
                "position": 2,
                "name": f"{w['machine']} Writeup",
                "item": f"{BASE_URL}/writeup/{w['slug']}/",
            },
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=None)


def json_ld_website() -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NAME,
        "url": BASE_URL,
        "description": "CTF writeups and security research — HackTheBox & TryHackMe",
        "author": {"@type": "Person", "name": AUTHOR},
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{BASE_URL}/?q={{search_term_string}}",
            },
            "query-input": "required name=search_term_string",
        },
    }
    return json.dumps(data, ensure_ascii=False, indent=None)


# ── Gedeelde HTML-fragmenten ──────────────────────────────────────────────────

_HEADER = """<header>
  <div class="container header-inner">
    <div style="display:flex;align-items:center;gap:20px">
      <div class="social-links">
        <a href="https://www.instagram.com/cyberstefan.nl/" target="_blank" rel="noopener" class="social-icon" title="Instagram">
          <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838a6.162 6.162 0 1 0 0 12.324 6.162 6.162 0 0 0 0-12.324zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.406-11.845a1.44 1.44 0 1 0 0 2.881 1.44 1.44 0 0 0 0-2.881z"/></svg>
        </a>
      </div>
      <a href="/" class="logo">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2"/>
          <path d="m8 21 4-4 4 4"/><path d="M7 7h.01"/><path d="M11 7h6"/><path d="M7 11h.01"/><path d="M11 11h6"/>
        </svg>
        CTF Writeups
      </a>
      <a href="/blog" style="color:var(--text-muted,#8b949e);font-size:.85rem;text-decoration:none;transition:color .15s" onmouseover="this.style.color='#e6edf3'" onmouseout="this.style.color='#8b949e'">Blog</a>
      <a href="/resources/" style="color:var(--text-muted,#8b949e);font-size:.85rem;text-decoration:none;transition:color .15s" onmouseover="this.style.color='#e6edf3'" onmouseout="this.style.color='#8b949e'">Resources</a>
    </div>
    <div style="display:flex;align-items:center;gap:16px">
      <div class="lang-flags-header">
        <button class="lang-flag-btn" data-lang="nl" title="Nederlands">
          <svg class="flag-svg-sm" viewBox="0 0 900 600"><rect width="900" height="600" fill="#21468B"/><rect width="900" height="400" fill="#fff"/><rect width="900" height="200" fill="#AE1C28"/></svg>
          <span class="lang-switch-code">NL</span>
        </button>
        <button class="lang-flag-btn" data-lang="en" title="English">
          <svg class="flag-svg-sm" viewBox="0 0 60 30"><rect width="60" height="30" fill="#012169"/><path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" stroke-width="6"/><path d="M0,0 L60,30 M60,0 L0,30" stroke="#C8102E" stroke-width="4"/><path d="M30,0 V30 M0,15 H60" stroke="#fff" stroke-width="10"/><path d="M30,0 V30 M0,15 H60" stroke="#C8102E" stroke-width="6"/></svg>
          <span class="lang-switch-code">EN</span>
        </button>
      </div>
    </div>
  </div>
</header>"""

_FOOTER = """<footer>
  <div class="container" id="footer-text">
    <span class="lang-en">Built with FastAPI &amp; SQLite &mdash; automated via <code>ctf-writeup</code> CLI</span>
    <span class="lang-nl" hidden>Gebouwd met FastAPI &amp; SQLite &mdash; geautomatiseerd via <code>ctf-writeup</code> CLI</span>
  </div>
</footer>"""

# Taalschakelaar — draait synchroon zodat er geen zichtbare flits is
_LANG_SCRIPT = """<script>
(function () {
  var l = localStorage.getItem('lang') || 'en';
  document.documentElement.lang = l;
  if (l === 'nl') {
    document.querySelectorAll('.lang-en').forEach(function(e){e.hidden=true;});
    document.querySelectorAll('.lang-nl').forEach(function(e){e.hidden=false;});
  }
  document.querySelectorAll('.lang-flag-btn').forEach(function(btn){
    btn.classList.toggle('active', btn.dataset.lang === l);
    btn.addEventListener('click', function(){
      var nl = btn.dataset.lang;
      localStorage.setItem('lang', nl);
      document.documentElement.lang = nl;
      document.querySelectorAll('.lang-flag-btn').forEach(function(b){
        b.classList.toggle('active', b.dataset.lang === nl);
      });
      document.querySelectorAll('.lang-en').forEach(function(e){e.hidden=(nl!=='en');});
      document.querySelectorAll('.lang-nl').forEach(function(e){e.hidden=(nl!=='nl');});
    });
  });
})();
</script>"""


# ── Writeup-pagina ────────────────────────────────────────────────────────────

def render_writeup_page(w: dict) -> str:
    slug = w["slug"]
    machine = _html.escape(w["machine"])
    platform = _html.escape(w["platform"])
    difficulty = _html.escape(w["difficulty"])
    canonical = f"{BASE_URL}/writeup/{slug}/"

    primary_text = w.get("writeup") or w.get("writeup_nl") or ""
    desc = _html.escape(make_description(primary_text))
    og_title = _html.escape(f"{w['machine']} CTF Writeup — {SITE_NAME}")
    page_title = f"{machine} — {platform} CTF Writeup | {SITE_NAME}"

    tags_html = "".join(
        f'<span class="badge badge-tag">{_html.escape(t)}</span>'
        for t in w.get("tags", [])
    )
    date_en = format_date(w.get("created_at", ""), "en")
    date_nl = format_date(w.get("created_at", ""), "nl")

    body_en = md_to_html(w.get("writeup") or "")
    body_nl = md_to_html(w.get("writeup_nl") or "") if w.get("writeup_nl") else ""

    aff_url = _html.escape(AFF.get(w["platform"], ""))
    cta_block = ""
    if aff_url:
        cta_block = f"""
  <div style="margin-top:32px;padding:18px 20px;background:#161b22;border:1px solid #30363d;border-radius:10px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
    <span class="lang-en" style="font-size:.9rem;color:#cdd9e5">Want to try this CTF challenge yourself?</span>
    <span class="lang-nl" hidden style="font-size:.9rem;color:#cdd9e5">Wil je deze CTF ook proberen?</span>
    <a href="{aff_url}" target="_blank" rel="noopener sponsored" style="display:inline-flex;align-items:center;gap:6px;background:#58a6ff;color:#0d1117;font-size:.82rem;font-weight:600;padding:8px 16px;border-radius:6px;text-decoration:none;white-space:nowrap">
      <span class="lang-en">Click here</span><span class="lang-nl" hidden>Ga dan hier naartoe</span>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
    </a>
  </div>"""

    nordvpn = _html.escape(AFF["NordVPN"])
    vpn_block = f"""
  <div style="margin-top:12px;padding:14px 18px;background:#0d1117;border:1px solid #21262d;border-radius:8px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
    <span class="lang-en" style="font-size:.82rem;color:#6e7681">🔒 Protect your IP while hacking — use a VPN</span>
    <span class="lang-nl" hidden style="font-size:.82rem;color:#6e7681">🔒 Bescherm je IP tijdens het hacken — gebruik een VPN</span>
    <a href="{nordvpn}" target="_blank" rel="noopener sponsored" style="font-size:.78rem;color:#58a6ff;text-decoration:none;white-space:nowrap;flex-shrink:0">NordVPN →</a>
  </div>"""

    nl_body_block = ""
    if body_nl:
        nl_body_block = f'\n  <div class="writeup-body lang-nl" hidden>{body_nl}</div>'

    return f"""<!DOCTYPE html>
<html lang="en" id="html-root">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{page_title}</title>
  <meta name="description" content="{desc}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="{SITE_NAME}">
  <meta property="og:title" content="{og_title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="{BASE_URL}/assets/cyberstefan-icon.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{og_title}">
  <meta name="twitter:description" content="{desc}">
  <meta name="twitter:image" content="{BASE_URL}/assets/cyberstefan-icon.png">
  <link rel="canonical" href="{canonical}">
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <link rel="icon" type="image/png" sizes="192x192" href="/favicon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/assets/style.css">
  <script type="application/ld+json">{json_ld_article(w)}</script>
  <script type="application/ld+json">{json_ld_breadcrumb(w)}</script>
</head>
<body>

{_HEADER}

<main class="container">
  <a href="/" class="back-link">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>
    <span class="lang-en">All writeups</span><span class="lang-nl" hidden>Alle writeups</span>
  </a>

  <div class="writeup-header">
    <h1 class="writeup-title">{machine}</h1>
    <div class="writeup-meta">
      <span class="badge badge-difficulty-{difficulty}">{difficulty}</span>
      <span class="badge badge-platform-{platform}">{platform}</span>
      <span class="badge" style="color:var(--muted);border-color:var(--border)">Completed</span>
    </div>
    {f'<div class="writeup-tags">{tags_html}</div>' if tags_html else ''}
    <p class="writeup-date" style="margin-top:10px">
      <span class="lang-en">{date_en}</span>
      <span class="lang-nl" hidden>{date_nl}</span>
    </p>
  </div>

  <div class="writeup-body lang-en">{body_en}</div>{nl_body_block}
{cta_block}
{vpn_block}
</main>

{_FOOTER}

{_LANG_SCRIPT}
</body>
</html>
"""


# ── Homepagina ────────────────────────────────────────────────────────────────

def _card(w: dict) -> str:
    tags = (w.get("tags") or [])
    tags_html = "".join(
        f'<span class="badge badge-tag">{_html.escape(t)}</span>'
        for t in tags[:4]
    )
    if len(tags) > 4:
        tags_html += f'<span class="badge badge-tag">+{len(tags) - 4}</span>'

    date_str = format_date(w.get("created_at", ""), "en")
    m = _html.escape(w["machine"])
    d = _html.escape(w["difficulty"])
    p = _html.escape(w["platform"])
    s = w["slug"]
    return f"""      <a class="card" href="/writeup/{s}/" data-platform="{p}" data-difficulty="{d}">
        <div class="card-header"><span class="card-title">{m}</span></div>
        <div class="card-meta">
          <span class="badge badge-difficulty-{d}">{d}</span>
          <span class="badge badge-platform-{p}">{p}</span>
        </div>
        {f'<div class="card-tags">{tags_html}</div>' if tags_html else ''}
        <span class="card-date">{date_str}</span>
      </a>"""


def render_index_page(writeups: list[dict]) -> str:
    cards_html = "\n".join(_card(w) for w in writeups)
    count = len(writeups)
    easy   = sum(1 for w in writeups if w["difficulty"] == "Easy")
    medium = sum(1 for w in writeups if w["difficulty"] == "Medium")
    hard   = sum(1 for w in writeups if w["difficulty"] == "Hard")
    tags_count = len({t for w in writeups for t in w.get("tags", [])})

    return f"""<!DOCTYPE html>
<html lang="en" id="html-root">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CTF Writeups | {SITE_NAME} — HackTheBox &amp; TryHackMe</title>
  <meta name="description" content="CTF writeups van CyberStefan — HackTheBox en TryHackMe machines stap voor stap uitgelegd: recon, exploitatie en privilege escalation.">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="{SITE_NAME}">
  <meta property="og:title" content="CTF Writeups | {SITE_NAME}">
  <meta property="og:description" content="HackTheBox &amp; TryHackMe writeups — ethical hacking stap voor stap uitgelegd.">
  <meta property="og:url" content="{BASE_URL}/">
  <meta property="og:image" content="{BASE_URL}/assets/cyberstefan-icon.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="CTF Writeups | {SITE_NAME}">
  <meta name="twitter:description" content="HackTheBox &amp; TryHackMe writeups — ethical hacking uitgelegd.">
  <meta name="impact-site-verification" value="{IMPACT_VERIFY_1}">
  <meta name="impact-site-verification" value="{IMPACT_VERIFY_2}">
  <link rel="canonical" href="{BASE_URL}/">
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <link rel="icon" type="image/png" sizes="192x192" href="/favicon.png">
  <link rel="apple-touch-icon" href="/favicon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/assets/style.css">
  <script type="application/ld+json">{json_ld_website()}</script>
</head>
<body>

{_HEADER}

<main class="container">
  <div class="hero">
    <h1>
      <span class="lang-en">Machine Writeups</span>
      <span class="lang-nl" hidden>Machine Writeups</span>
    </h1>
    <p>
      <span class="lang-en">HackTheBox &amp; TryHackMe &mdash; structured writeups documenting recon, exploitation, and privilege escalation.</span>
      <span class="lang-nl" hidden>HackTheBox &amp; TryHackMe &mdash; gestructureerde writeups over verkenning, exploitatie en privilege escalation.</span>
    </p>
  </div>

  <div class="stats-bar">
    <div class="stat">
      <span class="stat-value">{count}</span>
      <span class="stat-label"><span class="lang-en">Machines</span><span class="lang-nl" hidden>Machines</span></span>
    </div>
    <div class="stat">
      <span class="stat-value" style="color:var(--green)">{easy}</span>
      <span class="stat-label">Easy</span>
    </div>
    <div class="stat">
      <span class="stat-value" style="color:var(--yellow)">{medium}</span>
      <span class="stat-label">Medium</span>
    </div>
    <div class="stat">
      <span class="stat-value" style="color:var(--red)">{hard}</span>
      <span class="stat-label">Hard</span>
    </div>
    <div class="stat">
      <span class="stat-value">{tags_count}</span>
      <span class="stat-label"><span class="lang-en">Techniques</span><span class="lang-nl" hidden>Technieken</span></span>
    </div>
  </div>

  <div class="filters" id="filters">
    <button class="filter-btn active" data-filter="all">
      <span class="lang-en">All</span><span class="lang-nl" hidden>Alles</span>
    </button>
    <button class="filter-btn" data-filter="HackTheBox">HackTheBox</button>
    <button class="filter-btn" data-filter="TryHackMe">TryHackMe</button>
    <button class="filter-btn" data-filter="Easy">
      <span class="lang-en">Easy</span><span class="lang-nl" hidden>Makkelijk</span>
    </button>
    <button class="filter-btn" data-filter="Medium">
      <span class="lang-en">Medium</span><span class="lang-nl" hidden>Gemiddeld</span>
    </button>
    <button class="filter-btn" data-filter="Hard">
      <span class="lang-en">Hard</span><span class="lang-nl" hidden>Moeilijk</span>
    </button>
    <button class="filter-btn" data-filter="Insane">Insane</button>
  </div>

  <div id="root">
    <div class="cards">
{cards_html}
    </div>
  </div>
</main>

{_FOOTER}

<script>
// Filter — puur client-side op data-attributen, geen fetch nodig
document.getElementById('filters').addEventListener('click', function(e) {{
  var btn = e.target.closest('.filter-btn');
  if (!btn) return;
  document.querySelectorAll('.filter-btn').forEach(function(b){{ b.classList.remove('active'); }});
  btn.classList.add('active');
  var f = btn.dataset.filter;
  document.querySelectorAll('.card').forEach(function(card){{
    var show = f === 'all' || card.dataset.platform === f || card.dataset.difficulty === f;
    card.style.display = show ? '' : 'none';
  }});
}});
</script>

{_LANG_SCRIPT}
</body>
</html>
"""


# ── Sitemap ───────────────────────────────────────────────────────────────────

def render_sitemap(writeups: list[dict]) -> str:
    today = date.today().isoformat()
    writeup_entries = "\n".join(
        f"""  <url>
    <loc>{BASE_URL}/writeup/{w['slug']}/</loc>
    <lastmod>{w['created_at'][:10]}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>"""
        for w in writeups
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{BASE_URL}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{BASE_URL}/blog</loc>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>
  <url>
    <loc>{BASE_URL}/resources/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
{writeup_entries}
</urlset>
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="SSG voor cyberstefan.nl")
    parser.add_argument("--dry-run", action="store_true",
                        help="Toon wat er gegenereerd zou worden, schrijf niets")
    parser.add_argument("--writeup", metavar="SLUG_OR_ID",
                        help="Genereer alleen één writeup (slug of numeriek ID)")
    args = parser.parse_args()

    writeups = load_writeups()

    if args.writeup:
        writeups = [w for w in writeups
                    if w["slug"] == args.writeup or str(w["id"]) == args.writeup]
        if not writeups:
            print(f"Writeup niet gevonden: {args.writeup}")
            return

    generated: list[str] = []

    for w in writeups:
        out_dir  = WEB_DIR / "writeup" / w["slug"]
        out_file = out_dir / "index.html"
        content  = render_writeup_page(w)
        if args.dry_run:
            print(f"  [DRY] {out_file}  ({len(content):,} bytes)")
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file.write_text(content, encoding="utf-8")
            print(f"  ✓ {out_file}")
        generated.append(str(out_file))

    if not args.writeup:
        all_writeups = load_writeups()   # nieuw laden voor homepage/sitemap (ongefiltered)

        idx_file    = WEB_DIR / "index.html"
        idx_content = render_index_page(all_writeups)
        sm_file     = WEB_DIR / "sitemap.xml"
        sm_content  = render_sitemap(all_writeups)

        if args.dry_run:
            print(f"  [DRY] {idx_file}  ({len(idx_content):,} bytes)")
            print(f"  [DRY] {sm_file}  ({len(sm_content):,} bytes)")
        else:
            idx_file.write_text(idx_content, encoding="utf-8")
            print(f"  ✓ {idx_file}")
            sm_file.write_text(sm_content, encoding="utf-8")
            print(f"  ✓ {sm_file}")

    label = "[DRY RUN] Zou genereren" if args.dry_run else "Gegenereerd"
    extra = " + index.html + sitemap.xml" if not args.writeup else ""
    print(f"\n{label}: {len(generated)} writeup-pagina's{extra}")


if __name__ == "__main__":
    main()
