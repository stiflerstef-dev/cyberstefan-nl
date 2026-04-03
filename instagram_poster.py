"""Instagram poster via Instagram API with Instagram Login."""
import os
import time
import httpx
from datetime import datetime, timezone
from pathlib import Path

BASE     = "https://graph.instagram.com/v21.0"
ENV_FILE = Path("/etc/ctf-workflow.env")


def _token() -> str:
    return os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")


def _user_id() -> str:
    return os.environ.get("INSTAGRAM_USER_ID", "")


def _update_env(key: str, value: str):
    try:
        lines = ENV_FILE.read_text().splitlines()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}")
        ENV_FILE.write_text("\n".join(lines) + "\n")
    except PermissionError:
        print(f"[instagram] Geen schrijfrechten voor env — {key} niet opgeslagen")


def refresh_token() -> str:
    """Verleng de Instagram token (geldig voor 60 dagen).

    Roept de refresh endpoint aan en slaat de nieuwe token op.
    Geeft de nieuwe token terug.
    """
    token = _token()
    if not token:
        raise RuntimeError("Geen INSTAGRAM_ACCESS_TOKEN beschikbaar om te verlengen")

    r = httpx.get(f"{BASE}/refresh_access_token", params={
        "grant_type":   "ig_refresh_token",
        "access_token": token,
    }, timeout=30.0)
    r.raise_for_status()

    data      = r.json()
    new_token = data.get("access_token")
    expires   = data.get("expires_in", 5183944)  # ~60 dagen in seconden

    if not new_token:
        raise RuntimeError(f"Geen token in refresh-response: {r.text}")

    # Bewaar nieuwe token en vervaldatum
    _update_env("INSTAGRAM_ACCESS_TOKEN", new_token)
    expiry_ts = int(datetime.now(timezone.utc).timestamp()) + expires
    _update_env("INSTAGRAM_TOKEN_EXPIRES", str(expiry_ts))

    os.environ["INSTAGRAM_ACCESS_TOKEN"] = new_token
    os.environ["INSTAGRAM_TOKEN_EXPIRES"] = str(expiry_ts)

    expiry_date = datetime.fromtimestamp(expiry_ts).strftime("%Y-%m-%d")
    print(f"[instagram] Token verlengd, geldig tot {expiry_date}")
    return new_token


def _ensure_fresh_token() -> str:
    """Controleer of de token bijna verloopt en verleng hem automatisch (< 7 dagen)."""
    token      = _token()
    expires_ts = int(os.environ.get("INSTAGRAM_TOKEN_EXPIRES", "0"))
    now_ts     = int(datetime.now(timezone.utc).timestamp())
    days_left  = (expires_ts - now_ts) // 86400

    if expires_ts and days_left < 7:
        print(f"[instagram] Token verloopt over {days_left} dag(en), automatisch verlengen...")
        token = refresh_token()

    return token


def post_image(image_url: str, caption: str) -> dict:
    """Post een afbeelding met bijschrift op Instagram."""
    token   = _ensure_fresh_token()
    user_id = _user_id()

    if not token or not user_id:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN of INSTAGRAM_USER_ID niet geconfigureerd")

    # Stap 1 — maak media container
    r = httpx.post(f"{BASE}/{user_id}/media", data={
        "image_url":    image_url,
        "caption":      caption,
        "access_token": token,
    }, timeout=60.0)
    r.raise_for_status()
    container_id = r.json().get("id")
    if not container_id:
        raise RuntimeError(f"Geen container ID ontvangen: {r.text}")

    # Stap 2 — wacht tot container verwerkt is (max 30s)
    for _ in range(6):
        time.sleep(5)
        status = httpx.get(f"{BASE}/{container_id}", params={
            "fields":       "status_code",
            "access_token": token,
        }).json().get("status_code", "")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError("Instagram media container verwerkingsfout")

    # Stap 3 — publiceer
    r2 = httpx.post(f"{BASE}/{user_id}/media_publish", data={
        "creation_id":  container_id,
        "access_token": token,
    }, timeout=30.0)
    r2.raise_for_status()
    return r2.json()


def post_writeup(machine: str, difficulty: str, caption_nl: str, caption_en: str,
                 image_path: str = None) -> dict:
    """Post een CTF writeup op Instagram."""
    caption = caption_en if caption_en else caption_nl

    full_caption = caption.strip()
    hashtags = "\n\n🌐 cyberstefan.nl\n\n#CTF #HackTheBox #CyberSecurity #EthicalHacking #CyberStefan #Writeup #Pentesting"
    if len(full_caption) + len(hashtags) <= 2200:
        full_caption += hashtags

    if image_path:
        parts = Path(image_path).parts
        try:
            media_idx  = parts.index("media")
            writeup_id = parts[media_idx + 1]
            image_url  = f"https://cyberstefan.nl/api/writeups/{writeup_id}/image"
        except (ValueError, IndexError):
            image_url = "https://cyberstefan.nl/assets/cyberstefan-banner.jpg"
    else:
        image_url = "https://cyberstefan.nl/assets/cyberstefan-banner.jpg"

    return post_image(image_url, full_caption)
