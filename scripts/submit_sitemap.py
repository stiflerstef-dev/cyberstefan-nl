#!/usr/bin/env python3
"""
Dient de sitemap.xml in bij Google Search Console en stuurt een IndexNow-ping naar Bing.

Voorbereiding GSC:
  1. Ga naar https://search.google.com/search-console/
  2. Selecteer cyberstefan.nl → Instellingen → Gebruikers en machtigingen
  3. Zorg dat je eigenaar bent
  4. Maak een Service Account aan via https://console.cloud.google.com/
     - Activeer de "Google Search Console API"
     - Maak een Service Account, download het JSON-sleutelbestand
     - Geef het e-mailadres van de Service Account eigenaarrechten in GSC
  5. Sla het JSON-sleutelbestand op als:
       /etc/cyberstefan-gsc-key.json   (of gebruik de env var GSC_KEY_FILE)

Voorbereiding IndexNow (Bing):
  1. Genereer een API-sleutel op https://www.bing.com/indexnow
  2. Sla een tekstbestand op in je webroot:
       web/{api-key}.txt  met als inhoud de API-sleutel
  3. Zet de sleutel als env var: INDEXNOW_KEY=<jouw-sleutel>

Gebruik:
    python3 submit_sitemap.py           # GSC + IndexNow
    python3 submit_sitemap.py --gsc     # alleen Google
    python3 submit_sitemap.py --bing    # alleen Bing/IndexNow
"""

import argparse
import json
import os
import urllib.request
import urllib.error
from pathlib import Path

SITEMAP_URL = "https://cyberstefan.nl/sitemap.xml"
SITE_URL    = "https://cyberstefan.nl/"
GSC_KEY_FILE = os.environ.get("GSC_KEY_FILE", "/etc/cyberstefan-gsc-key.json")


# ── Google Search Console ──────────────────────────────────────────────────────

def submit_to_gsc() -> None:
    key_path = Path(GSC_KEY_FILE)
    if not key_path.exists():
        print(f"[GSC] Sleutelbestand niet gevonden: {key_path}")
        print("      Zie de instructies bovenaan dit bestand.")
        return

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("[GSC] Installeer eerst: pip install google-api-python-client google-auth")
        return

    creds = service_account.Credentials.from_service_account_file(
        str(key_path),
        scopes=["https://www.googleapis.com/auth/webmasters"],
    )
    service = build("searchconsole", "v1", credentials=creds)

    try:
        service.sitemaps().submit(siteUrl=SITE_URL, feedpath=SITEMAP_URL).execute()
        print(f"[GSC] ✓ Sitemap ingediend: {SITEMAP_URL}")
    except Exception as exc:
        print(f"[GSC] ✗ Fout: {exc}")

    # Toon bestaande sitemaps ter verificatie
    try:
        result = service.sitemaps().list(siteUrl=SITE_URL).execute()
        for sm in result.get("sitemap", []):
            print(f"[GSC]   ↳ {sm.get('path')}  status={sm.get('isPending')}")
    except Exception:
        pass


# ── IndexNow (Bing) ──────────────────────────────────────────────────────────

def submit_to_indexnow() -> None:
    api_key = os.environ.get("INDEXNOW_KEY", "")
    if not api_key:
        print("[Bing] Stel INDEXNOW_KEY in als env var (zie instructies bovenaan).")
        return

    payload = json.dumps({
        "host": "cyberstefan.nl",
        "key": api_key,
        "keyLocation": f"https://cyberstefan.nl/{api_key}.txt",
        "urlList": [
            "https://cyberstefan.nl/",
            "https://cyberstefan.nl/writeup/sau/",
            "https://cyberstefan.nl/writeup/busqueda/",
            "https://cyberstefan.nl/writeup/cap/",
            "https://cyberstefan.nl/writeup/support/",
        ],
    }).encode()

    req = urllib.request.Request(
        "https://api.indexnow.org/indexnow",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[Bing] ✓ IndexNow ping gestuurd  HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        print(f"[Bing] ✗ HTTP {exc.code}: {exc.read().decode()[:200]}")
    except Exception as exc:
        print(f"[Bing] ✗ Fout: {exc}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Sitemap indienen bij GSC en Bing")
    parser.add_argument("--gsc",  action="store_true", help="Alleen Google Search Console")
    parser.add_argument("--bing", action="store_true", help="Alleen Bing IndexNow")
    args = parser.parse_args()

    if not args.gsc and not args.bing:
        args.gsc = args.bing = True

    if args.gsc:
        submit_to_gsc()
    if args.bing:
        submit_to_indexnow()


if __name__ == "__main__":
    main()
