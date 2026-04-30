#!/usr/bin/env python3
"""Generate (or regenerate) the Instagram caption for any writeup.

Usage:
    python3 gen_instagram.py <writeup_id>
    python3 gen_instagram.py <writeup_id> --force   # overschrijf bestaande caption
    python3 gen_instagram.py --all                  # alle writeups zonder caption
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from media_generator import generate_instagram_caption
from openai import OpenAI

DB = Path(__file__).parent / "api" / "writeups.db"


def _client() -> OpenAI:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("[ERROR] OPENROUTER_API_KEY niet ingesteld", file=sys.stderr)
        sys.exit(1)
    return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")


def generate_for(writeup_id: int, force: bool = False) -> str:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM writeups WHERE id = ?", (writeup_id,)).fetchone()
    if not row:
        conn.close()
        print(f"[ERROR] Writeup {writeup_id} niet gevonden", file=sys.stderr)
        sys.exit(1)

    if row["linkedin"] and not force:
        print(f"[skip] Writeup {writeup_id} ({row['machine']}) heeft al een caption — gebruik --force om te overschrijven")
        conn.close()
        return row["linkedin"]

    client = _client()
    print(f"[gen] Instagram caption voor '{row['machine']}' ({row['difficulty']}, {row['platform']})...")
    caption = generate_instagram_caption(
        client, row["machine"], row["difficulty"], row["platform"], row["writeup"]
    )

    conn.execute("UPDATE writeups SET linkedin = ? WHERE id = ?", (caption, writeup_id))
    conn.commit()
    conn.close()

    print(f"[ok] Caption opgeslagen voor writeup {writeup_id}\n")
    print("=== Instagram Caption ===")
    print(caption)
    return caption


def main():
    parser = argparse.ArgumentParser(description="Genereer Instagram caption voor een CTF writeup")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("writeup_id", nargs="?", type=int, help="Writeup ID")
    group.add_argument("--all", action="store_true", help="Alle writeups zonder caption")
    parser.add_argument("--force", action="store_true", help="Overschrijf bestaande caption")
    args = parser.parse_args()

    if args.all:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, machine FROM writeups WHERE linkedin IS NULL OR linkedin = '' ORDER BY id"
        ).fetchall()
        conn.close()
        if not rows:
            print("Alle writeups hebben al een Instagram caption.")
            return
        for r in rows:
            generate_for(r["id"], force=False)
    else:
        generate_for(args.writeup_id, force=args.force)


if __name__ == "__main__":
    main()
