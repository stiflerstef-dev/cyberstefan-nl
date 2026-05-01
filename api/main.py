import json
import os
import subprocess
import sys
import httpx
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, HTTPException, Security, status
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import get_conn, init_db

app = FastAPI(title="CTF Writeups", docs_url=None, redoc_url=None)

MEDIA_DIR = Path(__file__).parent.parent / "media"
WEB_DIR   = Path(__file__).parent.parent / "web"

# ── CORS ────────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://cyberstefan.nl", "https://www.cyberstefan.nl"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# ── Auth ────────────────────────────────────────────────────────────────────────
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_api_key(key: Optional[str] = Security(API_KEY_HEADER)):
    expected = os.environ.get("CTF_API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="CTF_API_KEY not configured")
    if key != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return key

# ── Models ───────────────────────────────────────────────────────────────────────
class WriteupIn(BaseModel):
    machine:     str
    difficulty:  str
    platform:    str
    tags:        list[str] = []
    writeup:     str = ""
    writeup_nl:  str = ""
    linkedin:    str = ""
    linkedin_nl: str = ""
    status:      str = "Completed"

class WriteupOut(WriteupIn):
    id:         int
    created_at: str

# ── Startup ──────────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    init_db()
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# ── Writeup routes ───────────────────────────────────────────────────────────────
@app.get("/api/writeups", response_model=list[WriteupOut])
def list_writeups():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM writeups WHERE status = 'Completed' ORDER BY created_at DESC").fetchall()
    result = []
    for r in rows:
        row = dict(r)
        row["tags"] = json.loads(row["tags"])
        result.append(row)
    return result

@app.get("/api/writeups/{writeup_id}", response_model=WriteupOut)
def get_writeup(writeup_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM writeups WHERE id = ? AND status = 'Completed'", (writeup_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Writeup not found")
    result = dict(row)
    result["tags"] = json.loads(result["tags"])
    return result

@app.post("/api/writeups", response_model=WriteupOut, status_code=201)
def create_writeup(data: WriteupIn, background_tasks: BackgroundTasks,
                   _key: str = Security(require_api_key)):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO writeups (machine, difficulty, platform, tags, writeup, writeup_nl, linkedin, linkedin_nl, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.machine, data.difficulty, data.platform,
             json.dumps(data.tags), data.writeup, data.writeup_nl, data.linkedin, data.linkedin_nl, data.status),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM writeups WHERE id = ?", (cur.lastrowid,)).fetchone()
    result = dict(row)
    result["tags"] = json.loads(result["tags"])

    # Vertaling + media genereren op de achtergrond
    background_tasks.add_task(
        translate_and_generate_bg,
        result["id"], data.machine, data.difficulty, data.platform,
        data.writeup, data.writeup_nl
    )
    # Statische pagina's herbouwen zodat Google meteen goede HTML ziet
    background_tasks.add_task(_rebuild_static_pages)
    return result

@app.patch("/api/writeups/{writeup_id}", response_model=WriteupOut)
def patch_writeup(writeup_id: int, data: dict,
                  _key: str = Security(require_api_key)):
    allowed = {"machine", "difficulty", "platform", "tags", "writeup", "writeup_nl",
               "linkedin", "linkedin_nl", "status"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [writeup_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE writeups SET {set_clause} WHERE id = ?", values)
        conn.commit()
        row = conn.execute("SELECT * FROM writeups WHERE id = ?", (writeup_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Writeup not found")
    result = dict(row)
    result["tags"] = json.loads(result["tags"])
    return result

@app.delete("/api/writeups/{writeup_id}", status_code=204)
def delete_writeup(writeup_id: int, _key: str = Security(require_api_key)):
    import shutil
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM writeups WHERE id = ?", (writeup_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Writeup not found")
        conn.execute("DELETE FROM writeups WHERE id = ?", (writeup_id,))
        conn.commit()
    media_dir = MEDIA_DIR / str(writeup_id)
    if media_dir.exists():
        shutil.rmtree(media_dir)
    return Response(status_code=204)

# ── Media routes ─────────────────────────────────────────────────────────────────
@app.get("/api/writeups/{writeup_id}/media")
def get_media(writeup_id: int):
    manifest = MEDIA_DIR / str(writeup_id) / "manifest.json"
    if not manifest.exists():
        return {"status": "pending", "files": {}}
    return {"status": "ready", "files": json.loads(manifest.read_text())}

@app.post("/api/writeups/{writeup_id}/media", status_code=202)
def trigger_media(writeup_id: int, background_tasks: BackgroundTasks,
                  _key: str = Security(require_api_key)):
    """Hergenereert media voor een bestaande writeup."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM writeups WHERE id = ?", (writeup_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Writeup not found")
    w = dict(row)
    background_tasks.add_task(
        generate_media_bg,
        w["id"], w["machine"], w["difficulty"], w["platform"], w["writeup"]
    )
    return {"status": "generating"}

def translate_and_generate_bg(writeup_id, machine, difficulty, platform, writeup, writeup_nl):
    """Achtergrondtaak — vertaalt ontbrekende taal, genereert media en Instagram caption."""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from media_generator import translate_writeup, generate_all

        # Bepaal welke taal aangeleverd is en vertaal naar de andere
        if writeup and not writeup_nl:
            print(f"[translate] Vertaal EN → NL voor writeup {writeup_id}...")
            writeup_nl = translate_writeup(writeup, target_lang="nl")
            with get_conn() as conn:
                conn.execute("UPDATE writeups SET writeup_nl = ? WHERE id = ?", (writeup_nl, writeup_id))
                conn.commit()
            print(f"[translate] NL opgeslagen voor writeup {writeup_id}")
        elif writeup_nl and not writeup:
            print(f"[translate] Vertaal NL → EN voor writeup {writeup_id}...")
            writeup = translate_writeup(writeup_nl, target_lang="en")
            with get_conn() as conn:
                conn.execute("UPDATE writeups SET writeup = ? WHERE id = ?", (writeup, writeup_id))
                conn.commit()
            print(f"[translate] EN opgeslagen voor writeup {writeup_id}")

        media_result = generate_all(writeup_id, machine, difficulty, platform, writeup)

        # Sla gegenereerde Instagram caption op in de database
        if "instagram_caption" in media_result:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE writeups SET linkedin = ? WHERE id = ? AND (linkedin IS NULL OR linkedin = '')",
                    (media_result["instagram_caption"], writeup_id)
                )
                conn.commit()
            print(f"[instagram] Caption opgeslagen voor writeup {writeup_id}")

        # Haal writeup data op voor social posts
        with get_conn() as conn:
            row = conn.execute(
                "SELECT machine, difficulty, platform, linkedin, linkedin_nl FROM writeups WHERE id = ?",
                (writeup_id,)
            ).fetchone()

        if row:
            # TikTok post plaatsen
            try:
                from tiktok_poster import post_writeup as tiktok_post
                image_path = str(MEDIA_DIR / str(writeup_id) / "linkedin-image.jpg")
                tiktok_post(
                    row["machine"], row["difficulty"],
                    row["linkedin"],
                    image_path if Path(image_path).exists() else None
                )
                print(f"[tiktok] Post geplaatst voor writeup {writeup_id}")
            except Exception as e:
                print(f"[tiktok] Fout bij posten writeup {writeup_id}: {e}")

            # Instagram post plaatsen
            try:
                from instagram_poster import post_writeup as instagram_post
                image_path = str(MEDIA_DIR / str(writeup_id) / "linkedin-image.jpg")
                instagram_post(
                    row["machine"], row["difficulty"],
                    row["linkedin_nl"], row["linkedin"],
                    image_path if Path(image_path).exists() else None
                )
                print(f"[instagram] Post geplaatst voor writeup {writeup_id}")
            except Exception as e:
                print(f"[instagram] Fout bij posten writeup {writeup_id}: {e}")

    except Exception as e:
        print(f"[translate/media] Fout voor writeup {writeup_id}: {e}")

def generate_media_bg(writeup_id, machine, difficulty, platform, writeup):
    """Achtergrondtaak — genereert media zonder vertaling (voor hergenereatie)."""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from media_generator import generate_all
        generate_all(writeup_id, machine, difficulty, platform, writeup)
    except Exception as e:
        print(f"[media] Fout voor writeup {writeup_id}: {e}")

# ── Media image API endpoint (omzeilt NPM static file filtering) ─────────────────
@app.get("/api/writeups/{writeup_id}/image")
def get_writeup_image(writeup_id: int):
    image_path = MEDIA_DIR / str(writeup_id) / "linkedin-image.jpg"
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Afbeelding niet gevonden")
    return FileResponse(str(image_path), media_type="image/jpeg")


# ── Instagram OAuth ──────────────────────────────────────────────────────────────
@app.get("/instagram/callback")
async def instagram_callback(code: str = None, error: str = None, error_reason: str = None):
    if error:
        return HTMLResponse(f"<h2>Instagram autorisatie geweigerd</h2><p>{error_reason}</p>", status_code=400)
    if not code:
        return HTMLResponse("<h2>Geen code ontvangen</h2>", status_code=400)

    app_id     = os.environ.get("INSTAGRAM_APP_ID")
    app_secret = os.environ.get("INSTAGRAM_APP_SECRET")
    redirect   = "https://cyberstefan.nl/instagram/callback"

    # Stap 1 — wissel code in voor short-lived token
    async with httpx.AsyncClient() as client:
        r = await client.post("https://api.instagram.com/oauth/access_token", data={
            "client_id":     app_id,
            "client_secret": app_secret,
            "grant_type":    "authorization_code",
            "redirect_uri":  redirect,
            "code":          code,
        })
    if r.status_code != 200:
        return HTMLResponse(f"<h2>Token-aanvraag mislukt</h2><pre>{r.text}</pre>", status_code=500)

    token_data   = r.json()
    short_token  = token_data.get("access_token")
    user_id      = token_data.get("user_id")

    # Stap 2 — wissel in voor long-lived token (60 dagen)
    async with httpx.AsyncClient() as client:
        r2 = await client.get("https://graph.instagram.com/access_token", params={
            "grant_type":        "ig_exchange_token",
            "client_secret":     app_secret,
            "access_token":      short_token,
        })
    if r2.status_code != 200:
        return HTMLResponse(f"<h2>Long-lived token mislukt</h2><pre>{r2.text}</pre>", status_code=500)

    long_token = r2.json().get("access_token")

    # Sla op in env-bestand
    _update_env("INSTAGRAM_ACCESS_TOKEN", long_token)
    _update_env("INSTAGRAM_USER_ID", str(user_id))

    # Laad meteen in huidig proces
    os.environ["INSTAGRAM_ACCESS_TOKEN"] = long_token
    os.environ["INSTAGRAM_USER_ID"]      = str(user_id)

    return HTMLResponse(f"""
        <h2>Instagram gekoppeld!</h2>
        <p>User ID: <code>{user_id}</code></p>
        <p>Access token opgeslagen. Je kunt dit venster sluiten.</p>
    """)


# ── TikTok OAuth ─────────────────────────────────────────────────────────────────
@app.get("/tiktok/callback")
async def tiktok_callback(code: str = None, error: str = None, error_description: str = None):
    if error:
        return HTMLResponse(f"<h2>TikTok autorisatie geweigerd</h2><p>{error_description}</p>", status_code=400)
    if not code:
        return HTMLResponse("<h2>Geen code ontvangen</h2>", status_code=400)

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from tiktok_poster import exchange_code

    try:
        data = exchange_code(code)
    except Exception as e:
        return HTMLResponse(f"<h2>Token-aanvraag mislukt</h2><pre>{e}</pre>", status_code=500)

    access_token  = data.get("access_token")
    refresh_token = data.get("refresh_token")
    open_id       = data.get("open_id")

    _update_env("TIKTOK_ACCESS_TOKEN",  access_token)
    _update_env("TIKTOK_REFRESH_TOKEN", refresh_token)
    _update_env("TIKTOK_OPEN_ID",       str(open_id))

    os.environ["TIKTOK_ACCESS_TOKEN"]  = access_token
    os.environ["TIKTOK_REFRESH_TOKEN"] = refresh_token

    return HTMLResponse(f"""
        <h2>TikTok gekoppeld!</h2>
        <p>Open ID: <code>{open_id}</code></p>
        <p>Tokens opgeslagen. Je kunt dit venster sluiten.</p>
    """)


def _update_env(key: str, value: str):
    """Schrijft of updatet een KEY=value regel in /etc/ctf-workflow.env."""
    env_path = Path("/etc/ctf-workflow.env")
    try:
        lines = env_path.read_text().splitlines()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}")
        env_path.write_text("\n".join(lines) + "\n")
    except PermissionError:
        print(f"[env] Geen schrijfrechten voor /etc/ctf-workflow.env — {key} niet opgeslagen")


# ── Static: media bestanden ──────────────────────────────────────────────────────
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

# ── Static: Reveal.js self-hosted (via /api/reveal/ voor VPS-proxy compatibiliteit) ──
REVEAL_DIR = Path(__file__).parent.parent / "reveal"
app.mount("/api/reveal", StaticFiles(directory=str(REVEAL_DIR)), name="reveal-api")
app.mount("/reveal", StaticFiles(directory=str(REVEAL_DIR)), name="reveal")

# ── Static: web assets ───────────────────────────────────────────────────────────
app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")

@app.get("/writeup/{writeup_id}")
def serve_writeup_page(writeup_id: int):
    return FileResponse(str(WEB_DIR / "writeup.html"))

@app.get("/")
def serve_index():
    return FileResponse(str(WEB_DIR / "index.html"))
