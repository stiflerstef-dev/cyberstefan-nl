#!/usr/bin/env python3
"""
Dagelijkse controle voor cyberstefan.nl writeups.
Draait elke dag om 01:00 via cron.

Controleert:
1. Writeups zonder Engelse tekst  → vertaalt vanuit NL
2. Writeups zonder Nederlandse tekst → vertaalt vanuit EN
3. Writeups zonder Instagram caption → genereert deze

Logt alles naar /var/log/cyberstefan-daily.log
"""
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_FILE = Path("/var/log/cyberstefan-daily.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
WORKFLOW_DIR = Path(__file__).parent
DB           = WORKFLOW_DIR / "api" / "writeups.db"
sys.path.insert(0, str(WORKFLOW_DIR))


def _get_client():
    from openai import OpenAI
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        log.error("OPENROUTER_API_KEY niet ingesteld — stop.")
        sys.exit(1)
    return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")


def check_and_fix():
    from media_generator import translate_writeup, generate_instagram_caption

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    writeups = conn.execute("SELECT * FROM writeups ORDER BY id").fetchall()

    fixed_translation = 0
    fixed_caption     = 0

    for w in writeups:
        wid      = w["id"]
        machine  = w["machine"]
        has_en   = bool((w["writeup"]    or "").strip())
        has_nl   = bool((w["writeup_nl"] or "").strip())
        has_cap  = bool((w["linkedin"]   or "").strip())

        # ── Vertaling ────────────────────────────────────────────────────────
        if has_en and not has_nl:
            log.info(f"[{wid}] {machine}: NL ontbreekt — vertalen vanuit EN...")
            try:
                client   = _get_client()
                nl_text  = translate_writeup(w["writeup"], target_lang="nl")
                conn.execute("UPDATE writeups SET writeup_nl = ? WHERE id = ?", (nl_text, wid))
                conn.commit()
                log.info(f"[{wid}] {machine}: NL opgeslagen ({len(nl_text)} tekens)")
                fixed_translation += 1
            except Exception as e:
                log.error(f"[{wid}] {machine}: vertaling mislukt — {e}")

        elif has_nl and not has_en:
            log.info(f"[{wid}] {machine}: EN ontbreekt — vertalen vanuit NL...")
            try:
                client   = _get_client()
                en_text  = translate_writeup(w["writeup_nl"], target_lang="en")
                conn.execute("UPDATE writeups SET writeup = ? WHERE id = ?", (en_text, wid))
                conn.commit()
                log.info(f"[{wid}] {machine}: EN opgeslagen ({len(en_text)} tekens)")
                fixed_translation += 1
            except Exception as e:
                log.error(f"[{wid}] {machine}: vertaling mislukt — {e}")

        elif not has_en and not has_nl:
            log.warning(f"[{wid}] {machine}: BEIDE talen ontbreken — overgeslagen")

        # ── Instagram caption ─────────────────────────────────────────────────
        if not has_cap:
            source = (w["writeup"] or w["writeup_nl"] or "").strip()
            if not source:
                log.warning(f"[{wid}] {machine}: geen writeup tekst voor caption — overgeslagen")
                continue
            log.info(f"[{wid}] {machine}: Instagram caption ontbreekt — genereren...")
            try:
                client  = _get_client()
                caption = generate_instagram_caption(
                    client, machine, w["difficulty"], w["platform"], source
                )
                conn.execute("UPDATE writeups SET linkedin = ? WHERE id = ?", (caption, wid))
                conn.commit()
                log.info(f"[{wid}] {machine}: caption opgeslagen ({len(caption)} tekens)")
                fixed_caption += 1
            except Exception as e:
                log.error(f"[{wid}] {machine}: caption generatie mislukt — {e}")

    conn.close()

    log.info(
        f"Dagelijkse check klaar — "
        f"{fixed_translation} vertaling(en) aangevuld, "
        f"{fixed_caption} caption(s) aangevuld"
    )


if __name__ == "__main__":
    log.info("=== Dagelijkse writeup-check gestart ===")
    check_and_fix()
