#!/usr/bin/env python3
"""
CTF Writeup Automation Script
Usage: ctf-writeup -m <machine> -d <difficulty> -p <platform> -n <notes_file> [-t tag1,tag2]
"""

import argparse
import json
import os
import sys
import textwrap
from datetime import date
from pathlib import Path

import requests
from openai import OpenAI

FREE_MODELS = [
    "qwen/qwen3.6-plus:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "stepfun/step-3.5-flash:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
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

# ── Config ──────────────────────────────────────────────────────────────────────
API_BASE    = os.environ.get("CTF_API_URL", "http://localhost:8000")
WORKFLOW_DIR = Path.home() / "ctf-workflow"
WRITEUPS_DIR = WORKFLOW_DIR / "writeups"
LINKEDIN_DIR = WORKFLOW_DIR / "linkedin"

VALID_DIFFICULTIES = ["Easy", "Medium", "Hard", "Insane"]
VALID_PLATFORMS    = ["HackTheBox", "TryHackMe", "Other"]
VALID_TAGS         = ["SQLi", "RCE", "Buffer Overflow", "LFI", "SSRF",
                      "XSS", "Privesc", "Enumeration", "Web", "Linux"]

# ── Helpers ──────────────────────────────────────────────────────────────────────
def get_env(var: str) -> str:
    value = os.environ.get(var)
    if not value:
        print(f"[ERROR] Omgevingsvariabele {var} niet ingesteld.", file=sys.stderr)
        sys.exit(1)
    return value

def read_notes(path: str | None) -> str:
    if path:
        with open(path, "r") as f:
            return f.read().strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    print("[ERROR] Geen aantekeningen opgegeven. Gebruik -n <bestand> of pipe via stdin.", file=sys.stderr)
    sys.exit(1)

# ── Claude API calls ─────────────────────────────────────────────────────────────
def format_writeup(client: OpenAI, machine: str, difficulty: str,
                   platform: str, raw_notes: str) -> tuple[str, list[str]]:
    prompt = textwrap.dedent(f"""
        Jij bent degene die de machine "{machine}" ({difficulty}, {platform}) net zelf
        hebt gepakt. Schrijf je eigen writeup op basis van onderstaande ruwe
        aantekeningen — een verslag van wat JIJ deed, in het Engels.

        Stem en vorm:
        - Eerste persoon, verleden tijd ("I ran...", "I noticed...", "that took
          me a while"). Geen passieve vorm ("a shell was obtained" -> "I got a
          shell"). Geen "the target", schrijf "the box".
        - Wissel zinslengte af: korte, directe zinnen naast een enkele langere.
          Geen telkens even lange, perfect parallelle alinea's.
        - Mag een mening of irritatie bevatten als dat in de notities zit
          ("never seen this tool before", "this rabbit hole cost me an hour").

        Trouw aan de notities (belangrijk):
        - Verzin NIETS. Geen commando's, output, IP's, versies of stappen die
          niet in de aantekeningen staan. Liever korter en eerlijk dan compleet.
        - Neem echte artefacten letterlijk over: IP's, hostnames, versiestrings,
          foutmeldingen, commando-output. Geen <placeholders> als de echte
          waarde in de notities staat.
        - Staat er een verkeerd spoor, mislukte poging of iets dat tijd kostte
          in de notities -> laat dat staan, strijk het NIET glad.
        - Ontbreekt een fase in de notities, laat hem dan kort of weg. Schrijf
          niet "Not applicable" en vul niets in dat niet gebeurd is.

        Structuur (richtlijn, geen sjabloon):
        - Recon / Exploitation / Privilege Escalation / Lessons als losse draad,
          maar kopjes mogen informeel, samengevoegd of anders. Niet elke run
          dezelfde rigide opbouw.
        - Lessons Learned: hooguit 1-3 eerlijke takeaways uit wat JIJ opmerkte.
          GEEN rijtje vetgedrukte punten elk met een nette mitigatie eronder —
          dat leest als een gegenereerde preek.

        Vermijd deze woorden/wendingen volledig: notable, prime target,
        immediately interesting, seamless, robust, leverage, delve, "it's worth
        noting", "appears harmless but", "kill chain", en "Defense in depth" als
        los kopje.

        Eindig met een JSON-blok (```json) met de gebruikte technieken uit deze
        lijst: {VALID_TAGS}
        Formaat: {{"tags": ["tag1", "tag2"]}}

        Ruwe aantekeningen:
        ---
        {raw_notes}
        ---
    """).strip()

    full = ai_complete(client, [{"role": "user", "content": prompt}], max_tokens=2048)

    tags: list[str] = []
    if "```json" in full:
        json_block = full.split("```json")[1].split("```")[0].strip()
        try:
            detected = json.loads(json_block).get("tags", [])
            tags = [t for t in detected if t in VALID_TAGS]
        except json.JSONDecodeError:
            pass
        full = full.split("```json")[0].strip()

    return full, tags


def format_writeup_nl(client: OpenAI, machine: str, difficulty: str,
                     platform: str, raw_notes: str) -> str:
    prompt = textwrap.dedent(f"""
        Jij bent degene die de machine "{machine}" ({difficulty}, {platform}) net
        zelf hebt gepakt. Schrijf je eigen writeup in het Nederlands op basis van
        onderstaande ruwe aantekeningen. NIET vertalen uit het Engels — gewoon
        direct in het Nederlands schrijven zoals jij het zou vertellen.

        Stem en vorm:
        - Eerste persoon, verleden tijd ("ik scande...", "ik zag...", "dat duurde
          even"). Geen lijdende vorm. Schrijf "die box", niet "het doelwit" of
          "de aanvallende machine".
        - Informeel, gesproken Nederlands. Korte zinnen afgewisseld met een
          langere. Niet elke alinea even lang en perfect parallel.
        - Mag een mening of irritatie bevatten als die in de notities zit.

        Jargon blijft Engels — niet vertalen: shell, reverse shell, payload,
        pivoten, enumeraten, unauth RCE, privesc, foothold, listener, port,
        scan. Schrijf dus "ik kreeg een shell als puma", NIET "niet-
        geauthenticeerde OS-commando-injectie" of "de aanvallende machine".
        Tool-namen, commando's, CVE-nummers en output letterlijk laten staan.

        Trouw aan de notities (belangrijk):
        - Verzin NIETS. Geen stappen, commando's, output, IP's of versies die
          niet in de aantekeningen staan. Liever korter en eerlijk.
        - Echte artefacten letterlijk overnemen — geen <placeholders> als de
          echte waarde er staat.
        - Verkeerd spoor / mislukte poging / iets dat tijd kostte -> laten staan,
          niet gladstrijken. Ontbreekt een fase, laat hem kort of weg.

        Structuur is een richtlijn (verkenning / exploitatie / privesc / wat ik
        eruit haalde), geen vast sjabloon — kopjes mogen informeel of anders.
        Geen rijtje vetgedrukte "geleerde lessen" met nette mitigaties eronder.
        Geen JSON-blok aan het einde nodig.

        Ruwe aantekeningen:
        ---
        {raw_notes}
        ---
    """).strip()

    return ai_complete(client, [{"role": "user", "content": prompt}], max_tokens=2048)



# ── Local API ────────────────────────────────────────────────────────────────────
def push_to_api(api_key: str, machine: str, difficulty: str, platform: str,
                tags: list[str], writeup: str, linkedin: str, linkedin_nl: str = "") -> str:
    resp = requests.post(
        f"{API_BASE}/api/writeups",
        headers={"X-API-Key": api_key},
        json={
            "machine":     machine,
            "difficulty":  difficulty,
            "platform":    platform,
            "tags":        tags,
            "writeup":     writeup,
            "linkedin":    linkedin,
            "linkedin_nl": linkedin_nl,
            "status":      "Completed",
        },
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        print(f"[ERROR] API fout {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)
    writeup_id = resp.json()["id"]
    return f"{API_BASE}/writeup/{writeup_id}"

# ── Local backups ────────────────────────────────────────────────────────────────
def save_markdown(machine: str, difficulty: str, platform: str,
                  tags: list[str], writeup: str) -> Path:
    slug = machine.lower().replace(" ", "-")
    filename = WRITEUPS_DIR / f"{date.today().isoformat()}-{slug}.md"
    content = (
        f"# {machine}\n\n"
        f"**Platform:** {platform}  \n"
        f"**Difficulty:** {difficulty}  \n"
        f"**Date:** {date.today().isoformat()}  \n"
        f"**Tags:** {', '.join(tags) if tags else 'None'}  \n\n"
        "---\n\n"
        f"{writeup}\n"
    )
    filename.write_text(content, encoding="utf-8")
    return filename

def save_linkedin(machine: str, post: str) -> Path:
    slug = machine.lower().replace(" ", "-")
    filename = LINKEDIN_DIR / f"{date.today().isoformat()}-{slug}-linkedin.txt"
    filename.write_text(post, encoding="utf-8")
    return filename

# ── Main ─────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="CTF Writeup Automator — formatteert, pusht naar website, genereert LinkedIn post."
    )
    parser.add_argument("-m", "--machine",    required=True,  help="Machine naam (bijv. 'Busqueda')")
    parser.add_argument("-d", "--difficulty", required=True,  choices=VALID_DIFFICULTIES)
    parser.add_argument("-p", "--platform",   required=True,  choices=VALID_PLATFORMS)
    parser.add_argument("-n", "--notes",      default=None,   help="Pad naar ruwe aantekeningen (of pipe via stdin)")
    parser.add_argument("-t", "--tags",       default=None,   help="Handmatige tags, kommagescheiden (bijv. 'RCE,Privesc')")
    parser.add_argument("--no-api",           action="store_true", help="Sla website upload over (alleen lokale backup)")
    args = parser.parse_args()

    openrouter_key = get_env("OPENROUTER_API_KEY")
    api_key        = None if args.no_api else get_env("CTF_API_KEY")

    print(f"[1/4] Aantekeningen inlezen voor '{args.machine}'...")
    raw_notes = read_notes(args.notes)
    if not raw_notes:
        print("[ERROR] Aantekeningen zijn leeg.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=openrouter_key, base_url="https://openrouter.ai/api/v1")

    print("[2/5] Writeup formatteren via Claude API (EN)...")
    writeup, detected_tags = format_writeup(client, args.machine, args.difficulty, args.platform, raw_notes)

    manual_tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    all_tags    = list(dict.fromkeys(manual_tags + detected_tags))
    all_tags    = [t for t in all_tags if t in VALID_TAGS]

    print("[3/5] Nederlandse writeup schrijven (uit ruwe notities)...")
    writeup_nl = format_writeup_nl(client, args.machine, args.difficulty, args.platform, raw_notes)

    print("[4/4] Opslaan...")
    md_path = save_markdown(args.machine, args.difficulty, args.platform, all_tags, writeup)
    print(f"      Markdown backup : {md_path}")

    if not args.no_api:
        url = push_to_api(api_key, args.machine, args.difficulty, args.platform,
                          all_tags, writeup, "", "")
        print(f"      Website         : {url}")
        print("      Instagram caption wordt automatisch gegenereerd op de achtergrond.")

    print("\nKlaar!")

if __name__ == "__main__":
    main()
