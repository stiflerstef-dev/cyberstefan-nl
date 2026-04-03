"""TikTok poster via Content Posting API v2."""
import os
import httpx
from pathlib import Path

TOKEN_URL    = "https://open.tiktokapis.com/v2/oauth/token/"
POST_URL     = "https://open.tiktokapis.com/v2/post/publish/content/init/"
CREATOR_URL  = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
ENV_FILE     = Path("/etc/ctf-workflow.env")


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
        print(f"[tiktok] Geen schrijfrechten voor env — {key} niet opgeslagen")


def exchange_code(code: str) -> dict:
    """Wissel OAuth code in voor access + refresh token."""
    r = httpx.post(TOKEN_URL, data={
        "client_key":     os.environ.get("TIKTOK_CLIENT_KEY"),
        "client_secret":  os.environ.get("TIKTOK_CLIENT_SECRET"),
        "code":           code,
        "grant_type":     "authorization_code",
        "redirect_uri":   "https://cyberstefan.nl/tiktok/callback",
    }, timeout=30)
    r.raise_for_status()
    return r.json()


def refresh_token() -> str:
    """Verleng de TikTok access token via de refresh token."""
    refresh = os.environ.get("TIKTOK_REFRESH_TOKEN")
    if not refresh:
        raise RuntimeError("TIKTOK_REFRESH_TOKEN niet geconfigureerd")

    r = httpx.post(TOKEN_URL, data={
        "client_key":     os.environ.get("TIKTOK_CLIENT_KEY"),
        "client_secret":  os.environ.get("TIKTOK_CLIENT_SECRET"),
        "grant_type":     "refresh_token",
        "refresh_token":  refresh,
    }, timeout=30)
    r.raise_for_status()
    data = r.json()

    new_access  = data.get("access_token")
    new_refresh = data.get("refresh_token", refresh)

    _update_env("TIKTOK_ACCESS_TOKEN",  new_access)
    _update_env("TIKTOK_REFRESH_TOKEN", new_refresh)
    os.environ["TIKTOK_ACCESS_TOKEN"]  = new_access
    os.environ["TIKTOK_REFRESH_TOKEN"] = new_refresh

    print(f"[tiktok] Token verlengd")
    return new_access


def _token() -> str:
    return os.environ.get("TIKTOK_ACCESS_TOKEN", "")


def post_photo_carousel(images: list[str], caption: str) -> dict:
    """Post een foto-carousel op TikTok.

    images: lijst van publiek bereikbare HTTPS image URLs (max 35).
    caption: tekst bij de post (max 2200 tekens).
    """
    token = _token()
    if not token:
        raise RuntimeError("TIKTOK_ACCESS_TOKEN niet geconfigureerd")

    payload = {
        "post_info": {
            "title":        caption[:2200],
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet":   False,
            "disable_comment": False,
            "disable_stitch":  False,
        },
        "source_info": {
            "source":      "PULL_FROM_URL",
            "photo_cover_index": 0,
            "photo_images": images,
        },
        "media_type": "PHOTO",
    }

    r = httpx.post(POST_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json; charset=UTF-8",
        },
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def post_writeup(machine: str, difficulty: str, caption_en: str,
                 image_path: str = None) -> dict:
    """Post een CTF writeup als foto-carousel op TikTok."""

    # Bouw caption
    caption = caption_en.strip() if caption_en else f"{machine} - {difficulty} | HackTheBox"
    hashtags = "\n\n#CTF #HackTheBox #CyberSecurity #EthicalHacking #CyberStefan #Writeup"
    if len(caption) + len(hashtags) <= 2200:
        caption += hashtags

    # Bepaal afbeelding URL
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

    return post_photo_carousel([image_url], caption)
