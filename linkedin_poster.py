#!/usr/bin/env python3
"""
LinkedIn Poster — plaatst automatisch een post op LinkedIn bij een nieuwe writeup.
Gebruikt de LinkedIn UGC Posts API v2 met afbeelding-support.
"""

import os
import requests
from pathlib import Path

LINKEDIN_API = "https://api.linkedin.com/v2"
PERSON_URN   = "urn:li:person:K3tam-KuJ3"


def _headers(content_type: str = "application/json") -> dict:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("LINKEDIN_ACCESS_TOKEN niet geconfigureerd")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  content_type,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _upload_image(image_path: str) -> str:
    """Upload een afbeelding naar LinkedIn en geef het asset URN terug."""

    # Stap 1 — registreer upload
    reg = requests.post(
        f"{LINKEDIN_API}/assets?action=registerUpload",
        headers=_headers(),
        json={
            "registerUploadRequest": {
                "owner": PERSON_URN,
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "serviceRelationships": [{
                    "identifier":        "urn:li:userGeneratedContent",
                    "relationshipType":  "OWNER",
                }],
            }
        },
        timeout=15,
    )
    if reg.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn upload registratie mislukt {reg.status_code}: {reg.text[:200]}")

    data       = reg.json()["value"]
    asset_urn  = data["asset"]
    upload_url = data["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]

    # Stap 2 — upload binaire afbeelding
    with open(image_path, "rb") as f:
        put = requests.put(
            upload_url,
            headers={
                "Authorization": f"Bearer {os.environ.get('LINKEDIN_ACCESS_TOKEN')}",
                "Content-Type":  "application/octet-stream",
            },
            data=f,
            timeout=30,
        )
    if put.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn upload mislukt {put.status_code}: {put.text[:200]}")

    print(f"[linkedin] Afbeelding geüpload: {asset_urn}")
    return asset_urn


def post_to_linkedin(text: str, image_path: str = None) -> str:
    """Plaatst een post op LinkedIn, optioneel met afbeelding."""

    if image_path and Path(image_path).exists():
        try:
            asset_urn = _upload_image(image_path)
            media_category = "IMAGE"
            media = [{
                "status":      "READY",
                "description": {"text": "CTF Writeup"},
                "media":       asset_urn,
                "title":       {"text": text[:100]},
            }]
        except Exception as e:
            print(f"[linkedin] Afbeelding upload mislukt, post zonder: {e}")
            asset_urn      = None
            media_category = "NONE"
            media          = []
    else:
        media_category = "NONE"
        media          = []

    payload = {
        "author": PERSON_URN,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary":    {"text": text},
                "shareMediaCategory": media_category,
                **({"media": media} if media else {}),
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    resp = requests.post(
        f"{LINKEDIN_API}/ugcPosts",
        headers=_headers(),
        json=payload,
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn API fout {resp.status_code}: {resp.text[:300]}")

    post_id = resp.headers.get("x-restli-id", "")
    print(f"[linkedin] Post geplaatst: {post_id}")
    return post_id


def delete_post(post_id: str) -> bool:
    """Verwijder een LinkedIn post op basis van het post ID."""
    encoded = requests.utils.quote(post_id, safe="")
    resp = requests.delete(
        f"{LINKEDIN_API}/ugcPosts/{encoded}",
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code == 204:
        print(f"[linkedin] Post verwijderd: {post_id}")
        return True
    print(f"[linkedin] Verwijderen mislukt {resp.status_code}: {resp.text[:200]}")
    return False


def post_writeup(linkedin_nl: str, linkedin_en: str, image_path: str = None) -> str:
    """Post altijd de EN-versie met afbeelding als die beschikbaar is."""
    text = (linkedin_en or linkedin_nl or "").strip()
    if not text:
        raise ValueError("Geen LinkedIn-tekst beschikbaar om te posten")

    # Verwijder eventuele markdown-kopregel (# Titel)
    lines = text.splitlines()
    if lines and lines[0].startswith("#"):
        text = "\n".join(lines[1:]).strip()

    if "cyberstefan.nl" not in text:
        text += "\n\n🌐 https://cyberstefan.nl"

    return post_to_linkedin(text, image_path)
