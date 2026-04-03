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
        Je bent een senior penetration tester. Zet onderstaande ruwe CTF-aantekeningen om naar
        een gestructureerde writeup voor de machine "{machine}" ({difficulty}) op {platform}.

        Gebruik EXACT deze structuur (markdown headers):
        ## Recon
        ## Exploitation
        ## Privilege Escalation
        ## Lessons Learned

        Regels:
        - Schrijf in het Engels
        - Wees technisch precies maar leesbaar
        - Houd elke sectie gefocust; geen herhaling
        - Als een fase ontbreekt in de aantekeningen, schrijf dan "Not applicable" of vul in
          wat redelijkerwijs afgeleid kan worden
        - Eindig met een JSON-blok (```json) met de gebruikte technieken uit deze lijst:
          {VALID_TAGS}
          Formaat: {{"tags": ["tag1", "tag2"]}}

        Ruwe aantekeningen:
        ---
        {raw_notes}
        ---
    """).strip()

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    full = message.content[0].text

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
                     platform: str, writeup_en: str) -> str:
    prompt = textwrap.dedent(f"""
        Je bent een senior penetration tester. Vertaal en herschrijf onderstaande Engelstalige CTF writeup
        naar het Nederlands voor de machine "{machine}" ({difficulty}) op {platform}.

        Gebruik EXACT deze structuur (markdown headers):
        ## Recon
        ## Exploitation
        ## Privilege Escalation
        ## Lessons Learned

        Regels:
        - Schrijf in het Nederlands
        - Wees technisch precies maar leesbaar
        - Behoud alle technische termen, tool-namen, commando's en CVE-nummers onvertaald
        - Houd elke sectie gefocust; geen herhaling
        - Geen JSON-blok aan het einde nodig

        Engelstalige writeup:
        ---
        {writeup_en}
        ---
    """).strip()

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def generate_linkedin_post(client: anthropic.Anthropic, machine: str,
                           difficulty: str, platform: str, writeup: str,
                           language: str = "English") -> str:
    lang_rule = (
        "Write in English." if language == "English"
        else "Schrijf in het Nederlands."
    )
    prompt = textwrap.dedent(f"""
        Write a LinkedIn post based on the CTF writeup below.

        Rules:
        - Maximum 200 words
        - {lang_rule}
        - No technical jargon — focus on the learning process and growth mindset
        - Personal and authentic tone
        - End with 3-5 relevant hashtags (#ethicalhacking, #cybersecurity, etc.)
        - No bullet points, normal paragraphs
        - No "I am happy to announce" or other corporate-speak

        Context: machine "{machine}", difficulty {difficulty}, platform {platform}

        Writeup:
        ---
        {writeup[:1500]}
        ---
    """).strip()

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()

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

    anthropic_key = get_env("ANTHROPIC_API_KEY")
    api_key       = None if args.no_api else get_env("CTF_API_KEY")

    print(f"[1/4] Aantekeningen inlezen voor '{args.machine}'...")
    raw_notes = read_notes(args.notes)
    if not raw_notes:
        print("[ERROR] Aantekeningen zijn leeg.", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=anthropic_key)

    print("[2/5] Writeup formatteren via Claude API (EN)...")
    writeup, detected_tags = format_writeup(client, args.machine, args.difficulty, args.platform, raw_notes)

    manual_tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    all_tags    = list(dict.fromkeys(manual_tags + detected_tags))
    all_tags    = [t for t in all_tags if t in VALID_TAGS]

    print("[3/5] Writeup vertalen naar Nederlands...")
    writeup_nl = format_writeup_nl(client, args.machine, args.difficulty, args.platform, writeup)

    print("[4/5] LinkedIn posts genereren (EN + NL)...")
    linkedin_en = generate_linkedin_post(client, args.machine, args.difficulty, args.platform, writeup, "English")
    linkedin_nl = generate_linkedin_post(client, args.machine, args.difficulty, args.platform, writeup, "Dutch")

    print("[4/4] Opslaan...")
    md_path = save_markdown(args.machine, args.difficulty, args.platform, all_tags, writeup)
    li_path = save_linkedin(args.machine, linkedin_en + "\n\n---NL---\n\n" + linkedin_nl)
    print(f"      Markdown backup : {md_path}")
    print(f"      LinkedIn post   : {li_path}")

    if not args.no_api:
        url = push_to_api(api_key, args.machine, args.difficulty, args.platform,
                          all_tags, writeup, linkedin_en, linkedin_nl)
        print(f"      Website         : {url}")

    print("\nKlaar!")
    print("─" * 60)
    print("LINKEDIN (EN):")
    print("─" * 60)
    print(linkedin_en)
    print("─" * 60)
    print("LINKEDIN (NL):")
    print("─" * 60)
    print(linkedin_nl)
    print("─" * 60)

if __name__ == "__main__":
    main()
