#!/usr/bin/env python3
"""
Media Generator — maakt podcast scripts, audio en Reveal.js presentaties
van een CTF writeup. Twee versies: technisch en niet-technisch.

Vereisten:
  ANTHROPIC_API_KEY  — voor script + slide generatie
  ELEVENLABS_API_KEY — voor TTS audio
"""

import json
import os
import textwrap
from pathlib import Path

import requests
from openai import OpenAI

FREE_MODELS = [
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "openai/gpt-oss-120b:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

def ai_complete(client: OpenAI, messages: list, max_tokens: int = 2048) -> str:
    last_err = None
    for model in FREE_MODELS:
        try:
            resp = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
            return resp.choices[0].message.content.strip()
        except Exception as e:
            if any(c in str(e) for c in ["429", "404", "rate", "No endpoints"]):
                last_err = e
                continue
            raise
    raise last_err

MEDIA_DIR    = Path.home() / "ctf-workflow" / "media"
CLAUDE_MODEL = "claude-opus-4-6"

# ElevenLabs stemmen — gratis premade voices
VOICE_TECH     = "VR6AewLTigWG4xSOukaG"  # Arnold (man, diep) — technisch EN
VOICE_NONTECH  = "EXAVITQu4vr4xnSDxMaL"  # Bella (vrouw, helder) — niet-technisch NL

# ── Vertaling ────────────────────────────────────────────────────────────────────

def translate_writeup(text: str, target_lang: str) -> str:
    """Vertaalt een writeup naar de opgegeven taal ('nl' of 'en')."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    if target_lang == "nl":
        instruction = (
            "Vertaal de volgende CTF writeup van Engels naar Nederlands. "
            "Behoud alle technische termen, commando's, code blocks en opmaak (markdown) exact. "
            "Vertaal alleen de lopende tekst, titels en uitleg."
        )
    else:
        instruction = (
            "Translate the following CTF writeup from Dutch to English. "
            "Keep all technical terms, commands, code blocks and formatting (markdown) exactly as-is. "
            "Only translate the running text, titles and explanations."
        )

    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4096,
        messages=[{"role": "user", "content": f"{instruction}\n\n{text}"}]
    )
    return resp.content[0].text.strip()


# ── LinkedIn post generatie ───────────────────────────────────────────────────────

def generate_linkedin_post(client: anthropic.Anthropic, machine: str,
                           difficulty: str, platform: str, writeup: str) -> str:
    prompt = textwrap.dedent(f"""
        Write a LinkedIn post about solving the "{machine}" machine ({difficulty}) on {platform}.

        The post must combine technical depth with accessibility:
        - Open with a compelling hook (non-technical, relatable analogy or story)
        - Briefly explain what the challenge involved in plain language (1-2 sentences)
        - Include ONE concrete technical highlight: name the key vulnerability or technique
          (e.g. SSRF, CVE number, privilege escalation path) with a one-line explanation
          of what it means and why it matters in the real world
        - Close with a broader insight or takeaway relevant to both security professionals
          and curious non-technical readers
        - Add the URL on a separate line at the end: 🌐 https://cyberstefan.nl
        - Add relevant hashtags on the last line

        Style:
        - Conversational but credible tone
        - Max 1300 characters (LinkedIn optimal length)
        - No markdown headers or bullet points — flowing paragraphs
        - Written in English

        Writeup:
        ---
        {writeup}
        ---

        Return ONLY the post text, no extra explanation.
    """).strip()

    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text.strip()


# ── Claude scripts ────────────────────────────────────────────────────────────────

def generate_technical_script(client: anthropic.Anthropic, machine: str,
                               difficulty: str, platform: str, writeup: str) -> str:
    prompt = textwrap.dedent(f"""
        Schrijf een podcast-script van 3-4 minuten voor een technisch publiek (security professionals).

        Machine: {machine} | Difficulty: {difficulty} | Platform: {platform}

        Stijl:
        - Eén presenter, directe en technische toon
        - Bespreek: welke poorten/services gevonden, hoe de initiële toegang verkregen,
          welke exploit of techniek gebruikt, hoe privilege escalation werkte
        - Noem concrete tool-namen (nmap, gobuster, netcat, etc.) en commando-patronen
        - Eindig met de key takeaway voor security professionals
        - Schrijf in het Engels
        - GEEN [intro muziek] of productie-instructies — alleen gesproken tekst

        Writeup:
        ---
        {writeup}
        ---

        Geef ALLEEN de gesproken tekst terug, geen extra uitleg.
    """).strip()

    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text.strip()


def generate_nontechnical_script(client: anthropic.Anthropic, machine: str,
                                  difficulty: str, platform: str, writeup: str) -> str:
    prompt = textwrap.dedent(f"""
        Schrijf een podcast-script van 3-4 minuten voor een technisch publiek (security professionals).

        Machine: {machine} | Difficulty: {difficulty} | Platform: {platform}

        Stijl:
        - Eén presenter, directe en technische toon
        - Bespreek: welke poorten/services gevonden, hoe de initiële toegang verkregen,
          welke exploit of techniek gebruikt, hoe privilege escalation werkte
        - Noem concrete tool-namen (nmap, gobuster, netcat, etc.) en commando-patronen
        - Eindig met de key takeaway voor security professionals
        - Schrijf in het Nederlands
        - GEEN [intro muziek] of productie-instructies — alleen gesproken tekst

        Writeup:
        ---
        {writeup}
        ---

        Geef ALLEEN de gesproken tekst terug, geen extra uitleg.
    """).strip()

    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text.strip()


# ── ElevenLabs TTS ───────────────────────────────────────────────────────────────

def text_to_speech(api_key: str, text: str, voice_id: str, out_path: Path):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs fout {resp.status_code}: {resp.text[:200]}")
    out_path.write_bytes(resp.content)


# ── Reveal.js slides ─────────────────────────────────────────────────────────────

def generate_technical_slides(client: anthropic.Anthropic, machine: str,
                               difficulty: str, platform: str, writeup: str) -> list[dict]:
    prompt = textwrap.dedent(f"""
        Generate slide content for a technical presentation about CTF machine "{machine}".
        Write ALL titles and bullets in English.

        Return exactly 6 slides as a JSON array. Each slide has:
        - "title": slide title (short)
        - "bullets": list of 3-5 bullet points (technical, concrete)
        - "icon": one emoji matching the topic

        Slides in this order:
        1. Overview (machine info, difficulty, platform)
        2. Recon & Enumeration (discovered services, interesting ports)
        3. Initial Access (how access was gained, which vulnerability)
        4. Privilege Escalation (steps to root/admin)
        5. Tools & Techniques (tools used, command patterns)
        6. Lessons Learned (key takeaways for security professionals)

        Writeup:
        ---
        {writeup}
        ---

        Return ONLY the JSON array, nothing else.
    """).strip()

    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def generate_nontechnical_slides(client: anthropic.Anthropic, machine: str,
                                  difficulty: str, platform: str, writeup: str) -> list[dict]:
    prompt = textwrap.dedent(f"""
        Genereer slide-inhoud voor een niet-technische presentatie over CTF machine "{machine}".
        Doelgroep: mensen zonder IT-achtergrond.

        Geef exact 5 slides terug als JSON array. Elke slide heeft:
        - "title": slide titel (begrijpelijk, prikkelend)
        - "bullets": lijst van 3-4 punten (geen jargon, gebruik analogieën)
        - "icon": één emoji die bij het onderwerp past

        Slides:
        1. Wat is ethical hacking? (context geven)
        2. Het systeem (wat werd onderzocht en waarom)
        3. De zwakke plek (wat was het probleem, analogie gebruiken)
        4. Wat leerden we? (praktische lessen voor de echte wereld)
        5. Waarom dit belangrijk is (relevantie voor bedrijven/mensen)

        Writeup:
        ---
        {writeup}
        ---

        Geef ALLEEN de JSON array terug, niets anders.
    """).strip()

    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def generate_nontechnical_slides_en(client: anthropic.Anthropic, machine: str,
                                     difficulty: str, platform: str, writeup: str) -> list[dict]:
    prompt = textwrap.dedent(f"""
        Generate slide content for a non-technical presentation about CTF machine "{machine}".
        Target audience: people without an IT background (managers, clients, family).
        Write ALL titles and bullets in English.

        Return exactly 5 slides as a JSON array. Each slide has:
        - "title": slide title (clear, engaging)
        - "bullets": list of 3-4 points (no jargon, use analogies)
        - "icon": one emoji matching the topic

        Slides:
        1. What is ethical hacking? (give context)
        2. The system (what was investigated and why)
        3. The weak spot (what was the problem, use an analogy)
        4. What did we learn? (practical lessons for the real world)
        5. Why does this matter? (relevance for businesses and people)

        Writeup:
        ---
        {writeup}
        ---

        Return ONLY the JSON array, nothing else.
    """).strip()

    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


# ── HTML generatie ────────────────────────────────────────────────────────────────

def build_reveal_html(title: str, slides: list[dict], theme: str = "tech") -> str:
    bg     = "#0d1117" if theme == "tech" else "#1a1a2e"
    accent = "#58a6ff" if theme == "tech" else "#e94560"
    sub    = "Technical Deep-Dive" if theme == "tech" else "Voor iedereen"

    slides_html = f"""
    <section data-background="{bg}">
      <h1 style="color:{accent};font-family:'JetBrains Mono',monospace;font-size:1.8em">{title}</h1>
      <p style="color:#8b949e;margin-top:16px">{sub}</p>
    </section>
    """

    for s in slides:
        bullets = "".join(f"<li>{b}</li>" for b in s.get("bullets", []))
        slides_html += f"""
    <section data-background="{bg}">
      <h2 style="color:{accent}">{s.get('icon','')} {s.get('title','')}</h2>
      <ul style="color:#e6edf3;font-size:0.82em;line-height:1.5">{bullets}</ul>
    </section>
    """

    slides_html += f"""
    <section data-background="{bg}">
      <h2 style="color:{accent}">🏁 Done</h2>
      <p style="color:#8b949e">cyberstefan.nl</p>
    </section>
    """

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/black.css">
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;600&display=swap" rel="stylesheet">
  <style>
    .reveal {{ font-family: 'Inter', sans-serif; }}
    .reveal h1,.reveal h2 {{ font-family: 'JetBrains Mono', monospace; text-transform: none; margin-bottom: 0.3em; }}
    .reveal ul {{ list-style: none; padding: 0; margin: 0; width: 100%; }}
    .reveal ul li {{ word-wrap: break-word; overflow-wrap: break-word; white-space: normal; max-width: 100%; padding: 4px 0; }}
    .reveal ul li::before {{ content: "›  "; color: {accent}; font-weight: bold; }}
    .reveal section {{ text-align: left; padding: 20px 40px; box-sizing: border-box; }}
  </style>
</head>
<body>
<div style="position:fixed;top:14px;left:18px;z-index:9999;display:flex;gap:10px;align-items:center;">
  <a href="https://www.linkedin.com/in/cyber-stefan-094572400/" target="_blank" style="color:#8b949e;opacity:0.55;transition:opacity .2s;" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.55">
    <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
  </a>
  <a href="https://www.instagram.com/cyberstefan.nl/" target="_blank" style="color:#8b949e;opacity:0.55;transition:opacity .2s;" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.55">
    <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838a6.162 6.162 0 1 0 0 12.324 6.162 6.162 0 0 0 0-12.324zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.406-11.845a1.44 1.44 0 1 0 0 2.881 1.44 1.44 0 0 0 0-2.881z"/></svg>
  </a>
  <a href="https://www.tiktok.com/@cyberstefan.nl" target="_blank" style="color:#8b949e;opacity:0.55;transition:opacity .2s;" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.55">
    <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-2.88 2.5 2.89 2.89 0 0 1-2.89-2.89 2.89 2.89 0 0 1 2.89-2.89c.28 0 .54.04.79.1V9.01a6.33 6.33 0 0 0-.79-.05 6.34 6.34 0 0 0-6.34 6.34 6.34 6.34 0 0 0 6.34 6.34 6.34 6.34 0 0 0 6.33-6.34V8.69a8.18 8.18 0 0 0 4.78 1.52V6.75a4.85 4.85 0 0 1-1.01-.06z"/></svg>
  </a>
</div>
<div class="reveal">
  <div class="slides">
    {slides_html}
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
<script>Reveal.initialize({{ hash: true, transition: 'slide', backgroundTransition: 'fade', center: false, width: '100%', height: '100%', margin: 0.05, minScale: 0.1, maxScale: 1.5 }});</script>
</body>
</html>"""


# ── Hoofd functie ─────────────────────────────────────────────────────────────────

def generate_all(writeup_id: int, machine: str, difficulty: str,
                 platform: str, writeup: str) -> dict:
    """
    Genereert alle media voor een writeup en slaat op in ~/ctf-workflow/media/{id}/.
    Geeft een dict terug met de relatieve paden.
    """
    anthropic_key   = os.environ["ANTHROPIC_API_KEY"]
    elevenlabs_key  = os.environ.get("ELEVENLABS_API_KEY", "")

    out_dir = MEDIA_DIR / str(writeup_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = anthropic.Anthropic(api_key=anthropic_key)
    result = {}

    print("  [media] LinkedIn post genereren...")
    linkedin_en = generate_linkedin_post(client, machine, difficulty, platform, writeup)
    result["linkedin_en"] = linkedin_en

    print("  [media] Technisch podcast script...")
    tech_script = generate_technical_script(client, machine, difficulty, platform, writeup)
    (out_dir / "script-technical.txt").write_text(tech_script, encoding="utf-8")
    result["script_technical"] = f"media/{writeup_id}/script-technical.txt"

    print("  [media] Niet-technisch podcast script...")
    nontech_script = generate_nontechnical_script(client, machine, difficulty, platform, writeup)
    (out_dir / "script-nontechnical.txt").write_text(nontech_script, encoding="utf-8")
    result["script_nontechnical"] = f"media/{writeup_id}/script-nontechnical.txt"

    if elevenlabs_key:
        for label, script, voice, filename, key in [
            ("technisch",       tech_script,    VOICE_TECH,    "podcast-technical.mp3",    "audio_technical"),
            ("niet-technisch",  nontech_script, VOICE_NONTECH, "podcast-nontechnical.mp3", "audio_nontechnical"),
        ]:
            out_path = out_dir / filename
            if out_path.exists():
                print(f"  [media] Audio ({label}) al aanwezig, overgeslagen")
                result[key] = f"media/{writeup_id}/{filename}"
                continue
            print(f"  [media] Audio genereren ({label})...")
            try:
                text_to_speech(elevenlabs_key, script, voice, out_path)
                result[key] = f"media/{writeup_id}/{filename}"
            except RuntimeError as e:
                print(f"  [media] Audio ({label}) mislukt: {e}")
    else:
        print("  [media] ELEVENLABS_API_KEY niet ingesteld — audio overgeslagen")

    print("  [media] Technische slides...")
    tech_slides = generate_technical_slides(client, machine, difficulty, platform, writeup)
    html = build_reveal_html(machine, tech_slides, theme="tech")
    (out_dir / "slides-technical.html").write_text(html, encoding="utf-8")
    result["slides_technical"] = f"media/{writeup_id}/slides-technical.html"

    print("  [media] Niet-technische slides (NL)...")
    nontech_slides_nl = generate_nontechnical_slides(client, machine, difficulty, platform, writeup)
    html = build_reveal_html(machine, nontech_slides_nl, theme="nontech")
    (out_dir / "slides-nontechnical-nl.html").write_text(html, encoding="utf-8")
    result["slides_nontechnical_nl"] = f"media/{writeup_id}/slides-nontechnical-nl.html"

    print("  [media] Niet-technische slides (EN)...")
    nontech_slides_en = generate_nontechnical_slides_en(client, machine, difficulty, platform, writeup)
    html = build_reveal_html(machine, nontech_slides_en, theme="nontech")
    (out_dir / "slides-nontechnical-en.html").write_text(html, encoding="utf-8")
    result["slides_nontechnical_en"] = f"media/{writeup_id}/slides-nontechnical-en.html"

    # Sla manifest op zodat de site weet wat beschikbaar is
    (out_dir / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"  [media] Klaar — {len(result)} bestanden in {out_dir}")

    return result


if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--id",         type=int,  required=True)
    parser.add_argument("--machine",    required=True)
    parser.add_argument("--difficulty", required=True)
    parser.add_argument("--platform",  required=True)
    parser.add_argument("--writeup",   required=True, help="Pad naar writeup tekstbestand")
    args = parser.parse_args()
    writeup_text = Path(args.writeup).read_text(encoding="utf-8")
    result = generate_all(args.id, args.machine, args.difficulty, args.platform, writeup_text)
    print(json.dumps(result, indent=2))
