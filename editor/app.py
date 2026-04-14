#!/usr/bin/env python3
"""
CTF Writeup Upload Server — LAN-only
Vervangt Notion als schrijfomgeving voor CTF writeups.
Draait op poort 8082, alleen bereikbaar via LAN.
"""

import os
import re
import json
import uuid
import fcntl
import struct
import termios
import asyncio
import queue
import threading
import mimetypes
import subprocess
import signal
from pathlib import Path
from datetime import datetime

import hashlib
import secrets as _secrets

import itsdangerous
import duo_universal as _duo
import requests
import ptyprocess
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

# ── AI setup ─────────────────────────────────────────────────────────────────
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
FREE_MODELS = [
    "stepfun/step-3.5-flash:free",
    "qwen/qwen3.6-plus:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "google/gemma-3-27b-it:free",
]

def ai_complete(messages: list, max_tokens: int = 1024) -> str:
    client = OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
    last_err = None
    for model in FREE_MODELS:
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            if any(c in str(e) for c in ["429", "404", "rate", "No endpoints"]):
                last_err = e
                continue
            raise
    raise last_err or RuntimeError("Geen AI-model beschikbaar")

# ── App setup ─────────────────────────────────────────────────────────────────
UPLOAD_DIR    = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

DOWNLOAD_DIR  = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

CTF_API_URL = os.environ.get("CTF_API_URL", "http://localhost:8000")
CTF_API_KEY = os.environ.get("CTF_API_KEY", "")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "https://cyberstefan.nl/ctf-uploads")

app = FastAPI(title="CTF Writeup Editor")
app.mount("/ctf-uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/downloads", StaticFiles(directory=str(DOWNLOAD_DIR)), name="downloads")

# ── Auth config ───────────────────────────────────────────────────────────────
_SESSION_SECRET  = os.environ.get("SESSION_SECRET", _secrets.token_hex(32))
_ADMIN_USER      = os.environ.get("ADMIN_USERNAME", "")
_ADMIN_PW_HASH   = os.environ.get("ADMIN_PASSWORD_HASH", "")   # sha256 hex van wachtwoord
_DUO_CLIENT_ID   = os.environ.get("DUO_CLIENT_ID", "")
_DUO_CLIENT_SEC  = os.environ.get("DUO_CLIENT_SECRET", "")
_DUO_API_HOST    = os.environ.get("DUO_API_HOST", "")
_DUO_REDIRECT    = os.environ.get("DUO_REDIRECT_URI", "https://cyberstefan.nl/auth/duo/callback")

_AUTH_ENABLED = bool(_ADMIN_USER and _ADMIN_PW_HASH)
_DUO_ENABLED  = bool(_DUO_CLIENT_ID and _DUO_CLIENT_SEC and _DUO_API_HOST)
_signer       = itsdangerous.URLSafeTimedSerializer(_SESSION_SECRET)
_PUBLIC_PATHS = {"/login", "/auth/duo/callback"}


def _get_session(request: Request) -> dict | None:
    token = request.cookies.get("_cs_session")
    if not token:
        return None
    try:
        return _signer.loads(token, max_age=28800)  # 8 uur
    except Exception:
        return None


def _make_duo_client() -> _duo.Client:
    return _duo.Client(
        client_id=_DUO_CLIENT_ID,
        client_secret=_DUO_CLIENT_SEC,
        host=_DUO_API_HOST,
        redirect_uri=_DUO_REDIRECT,
    )


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not _AUTH_ENABLED:
        return await call_next(request)
    # WebSocket upgrade requests komen binnen als HTTP maar moeten doorgelaten worden —
    # auth zit rechtstreeks in de WebSocket-handler
    if (request.scope.get("type") == "websocket"
            or request.headers.get("upgrade", "").lower() == "websocket"):
        return await call_next(request)
    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith("/ctf-uploads/"):
        return await call_next(request)
    session = _get_session(request)
    if session and session.get("authenticated"):
        return await call_next(request)
    # JSON API-paden krijgen 401, browserpaden krijgen redirect
    _API_PREFIXES = ("/terminal/", "/hint", "/analyze", "/submit", "/upload/",
                     "/downloads/", "/writeups", "/cards")
    if any(path.startswith(p) for p in _API_PREFIXES):
        return JSONResponse({"detail": "Niet ingelogd"}, status_code=401)
    return RedirectResponse(url="/login", status_code=302)

# ── Card cache ────────────────────────────────────────────────────────────────
CARD_CACHE_FILE = Path(__file__).parent / "card_cache.json"
_card_cache: list = []
_card_generation_lock = asyncio.Lock()

def _load_card_cache() -> list:
    if CARD_CACHE_FILE.exists():
        try:
            return json.loads(CARD_CACHE_FILE.read_text())
        except Exception:
            return []
    return []

def _save_card_cache(cards: list):
    CARD_CACHE_FILE.write_text(json.dumps(cards, ensure_ascii=False))


# ── Image upload ──────────────────────────────────────────────────────────────
@app.post("/upload/image")
async def upload_image(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Alleen afbeeldingen toegestaan")
    ext      = mimetypes.guess_extension(file.content_type) or ".png"
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    dest     = UPLOAD_DIR / filename
    dest.write_bytes(await file.read())
    return {"url": f"{PUBLIC_BASE}/{filename}", "filename": filename}


# ── Writeup submit ────────────────────────────────────────────────────────────
@app.post("/submit")
async def submit_writeup(request: Request):
    body = await request.json()
    for field in ["machine", "difficulty", "platform", "writeup"]:
        if not body.get(field):
            raise HTTPException(status_code=400, detail=f"Veld '{field}' is verplicht")
    try:
        r = requests.post(
            f"{CTF_API_URL}/api/writeups",
            json={
                "machine":    body["machine"],
                "difficulty": body["difficulty"],
                "platform":   body["platform"],
                "tags":       body.get("tags", []),
                "writeup":    body["writeup"],
                "writeup_nl": body.get("writeup_nl", ""),
                "linkedin":   body.get("linkedin", ""),
                "linkedin_nl": body.get("linkedin_nl", ""),
            },
            headers={"X-API-Key": CTF_API_KEY, "Content-Type": "application/json"},
            timeout=15,
        )
        r.raise_for_status()
        result = r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"CTF API fout: {e}")

    # Leeg de tijdelijke download folder na publicatie
    removed = 0
    for f in DOWNLOAD_DIR.iterdir():
        if f.is_file():
            try:
                f.unlink()
                removed += 1
            except Exception:
                pass

    return JSONResponse({"ok": True, "id": result.get("id"), "machine": result.get("machine"), "downloads_cleared": removed})


# ── VPN ───────────────────────────────────────────────────────────────────────
VPN_DIR = Path(__file__).parent / "vpn_configs"
VPN_DIR.mkdir(exist_ok=True)

_VPN_STATE: dict = {
    "status": "disconnected",   # disconnected | connecting | connected | error
    "config": None,
    "ip": None,
    "pid": None,
    "log_tail": "",
}

# Directives that allow arbitrary command execution or privilege escalation.
# Blocklist used during config validation — any match rejects the upload.
_VPN_BLOCKED_RE = re.compile(
    r"^\s*("
    r"script-security\s+[1-9]"          # enables script hooks
    r"|up\s+"                            # connect script
    r"|down\s+"                          # disconnect script
    r"|route-up\s+"                      # route script
    r"|ipchange\s+"                      # IP-change script
    r"|route-pre-down\s+"
    r"|tls-verify\s+"                    # TLS verify script
    r"|auth-user-pass-verify\s+"         # auth script
    r"|client-connect\s+"
    r"|client-disconnect\s+"
    r"|learn-address\s+"
    r"|plugin\s+"                        # load arbitrary .so
    r"|management\s+"                    # management socket
    r"|iproute\s+"                       # replace ip command
    r"|writepid\s+"                      # write PID to arbitrary path
    r"|cd\s+"                            # change working dir
    r"|tmp-dir\s+"                       # change tmp location
    r")",
    re.IGNORECASE,
)

# Directives where the value is a filesystem path (external file).
# Inline (<ca>…</ca>) blocks are fine — external paths pointing outside
# the VPN config dir are rejected to prevent path traversal / secrets leak.
_VPN_PATH_DIRECTIVES = re.compile(
    r"^\s*(ca|cert|key|tls-auth|tls-crypt|tls-crypt-v2|dh|pkcs12)\s+(.+)$",
    re.IGNORECASE,
)

_VPN_LOG = Path(__file__).parent / "vpn.log"
_VPN_START_SCRIPT = Path(__file__).parent.parent / "scripts" / "vpn-start.sh"
_VPN_STOP_SCRIPT  = Path(__file__).parent.parent / "scripts" / "vpn-stop.sh"


def _validate_ovpn(content: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message). Empty error means valid."""
    if len(content.encode()) > 200_000:
        return False, "Bestand te groot (max 200 KB)"

    lines = content.splitlines()

    # Must have at minimum a 'remote' directive — basic sanity check
    has_remote = any(re.match(r"^\s*remote\s+", l, re.IGNORECASE) for l in lines)
    if not has_remote:
        return False, "Geen geldige OpenVPN config: 'remote' directive ontbreekt"

    inside_inline_block = False
    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        # Track inline certificate blocks — path rules don't apply inside them
        if line.startswith("<") and not line.startswith("</"):
            inside_inline_block = True
        if line.startswith("</"):
            inside_inline_block = False
            continue
        if inside_inline_block:
            continue

        # Reject dangerous directives
        if _VPN_BLOCKED_RE.match(raw):
            directive = line.split()[0]
            return False, (
                f"Regel {lineno}: directive '{directive}' is geblokkeerd "
                f"om veiligheidsredenen (command injection risico)"
            )

        # Reject external path references outside the VPN dir
        m = _VPN_PATH_DIRECTIVES.match(raw)
        if m:
            ref_path = m.group(2).strip().strip('"').strip("'")
            # Resolve relative to VPN_DIR
            resolved = (VPN_DIR / ref_path).resolve()
            if not str(resolved).startswith(str(VPN_DIR.resolve())):
                directive = m.group(1)
                return False, (
                    f"Regel {lineno}: '{directive}' verwijst naar een bestand buiten "
                    f"de VPN config map. Gebruik inline <{directive.lower()}>…</{directive.lower()}> blokken."
                )

    return True, ""


def _vpn_detect_ip() -> str | None:
    """Try to find the TUN interface IP (tun0 or similar)."""
    try:
        out = subprocess.check_output(
            ["ip", "-4", "addr", "show", "type", "tun"],
            text=True, stderr=subprocess.DEVNULL, timeout=3,
        )
        m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None
    except Exception:
        return None


def _vpn_read_log(tail: int = 20) -> str:
    """Return last N lines of the VPN log."""
    if not _VPN_LOG.exists():
        return ""
    try:
        lines = _VPN_LOG.read_text(errors="replace").splitlines()
        return "\n".join(lines[-tail:])
    except Exception:
        return ""


@app.post("/vpn/upload")
async def vpn_upload(request: Request, file: UploadFile = File(...)):
    """Upload and validate a .ovpn config file."""
    session = _get_session(request)
    if _AUTH_ENABLED and (not session or not session.get("authenticated")):
        raise HTTPException(403, "Niet ingelogd")

    if not file.filename or not file.filename.lower().endswith(".ovpn"):
        raise HTTPException(400, "Alleen .ovpn bestanden zijn toegestaan")

    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Bestand is geen geldige UTF-8 tekst")

    ok, err = _validate_ovpn(content)
    if not ok:
        raise HTTPException(422, f"Config geweigerd: {err}")

    # Sanitize filename: only alphanumeric, dash, underscore
    safe_stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", Path(file.filename).stem)
    safe_name = safe_stem[:64] + ".ovpn"
    dest = VPN_DIR / safe_name
    dest.write_text(content, encoding="utf-8")

    return {"ok": True, "name": safe_name}


@app.get("/vpn/configs")
async def vpn_configs(request: Request):
    """List available VPN configs."""
    session = _get_session(request)
    if _AUTH_ENABLED and (not session or not session.get("authenticated")):
        raise HTTPException(403, "Niet ingelogd")

    configs = []
    for f in sorted(VPN_DIR.glob("*.ovpn")):
        # Determine platform from filename
        name_lower = f.name.lower()
        if "tryhackme" in name_lower or "thm" in name_lower:
            platform = "TryHackMe"
        elif "hackthebox" in name_lower or "htb" in name_lower:
            platform = "HackTheBox"
        else:
            platform = "Overig"
        configs.append({"name": f.name, "platform": platform, "size": f.stat().st_size})

    return {"configs": configs}


@app.delete("/vpn/configs/{name}")
async def vpn_delete_config(name: str, request: Request):
    """Delete a saved VPN config."""
    session = _get_session(request)
    if _AUTH_ENABLED and (not session or not session.get("authenticated")):
        raise HTTPException(403, "Niet ingelogd")

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", Path(name).stem) + ".ovpn"
    target = VPN_DIR / safe_name
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "Config niet gevonden")
    # Safety: must be inside VPN_DIR
    if not str(target.resolve()).startswith(str(VPN_DIR.resolve())):
        raise HTTPException(400, "Ongeldige padnaam")
    target.unlink()
    return {"ok": True}


@app.post("/vpn/connect")
async def vpn_connect(request: Request):
    """Start OpenVPN with the selected config."""
    session = _get_session(request)
    if _AUTH_ENABLED and (not session or not session.get("authenticated")):
        raise HTTPException(403, "Niet ingelogd")

    body = await request.json()
    config_name = body.get("config", "")
    if not config_name:
        raise HTTPException(400, "Geen config opgegeven")

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", Path(config_name).stem) + ".ovpn"
    config_path = VPN_DIR / safe_name
    if not config_path.exists():
        raise HTTPException(404, "Config niet gevonden")

    # Verify the wrapper script exists
    if not _VPN_START_SCRIPT.exists():
        raise HTTPException(503, "vpn-start.sh niet gevonden — zie setup instructies")

    # Kill any existing VPN process
    if _VPN_STATE.get("pid"):
        try:
            os.kill(_VPN_STATE["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
        _VPN_STATE["pid"] = None

    # Clear old log
    try:
        _VPN_LOG.write_text("")
    except Exception:
        pass

    try:
        proc = subprocess.Popen(
            ["sudo", str(_VPN_START_SCRIPT), str(config_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _VPN_STATE["status"] = "connecting"
        _VPN_STATE["config"] = safe_name
        _VPN_STATE["pid"] = proc.pid
        _VPN_STATE["ip"] = None
        _VPN_STATE["log_tail"] = ""
        return {"ok": True, "status": "connecting"}
    except Exception as e:
        _VPN_STATE["status"] = "error"
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/vpn/disconnect")
async def vpn_disconnect(request: Request):
    """Stop the active OpenVPN connection."""
    session = _get_session(request)
    if _AUTH_ENABLED and (not session or not session.get("authenticated")):
        raise HTTPException(403, "Niet ingelogd")

    if not _VPN_STOP_SCRIPT.exists():
        raise HTTPException(503, "vpn-stop.sh niet gevonden — zie setup instructies")

    try:
        subprocess.run(
            ["sudo", str(_VPN_STOP_SCRIPT)],
            timeout=10, check=False,
            capture_output=True,
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    _VPN_STATE["status"] = "disconnected"
    _VPN_STATE["ip"] = None
    _VPN_STATE["pid"] = None
    return {"ok": True, "status": "disconnected"}


@app.get("/vpn/status")
async def vpn_status(request: Request):
    """Return current VPN connection state."""
    session = _get_session(request)
    if _AUTH_ENABLED and (not session or not session.get("authenticated")):
        raise HTTPException(403, "Niet ingelogd")

    ip = _vpn_detect_ip()
    if ip:
        _VPN_STATE["status"] = "connected"
        _VPN_STATE["ip"] = ip
    elif _VPN_STATE["status"] == "connected":
        # Was connected but TUN is gone
        _VPN_STATE["status"] = "disconnected"
        _VPN_STATE["ip"] = None

    _VPN_STATE["log_tail"] = _vpn_read_log()
    return {
        "status": _VPN_STATE["status"],
        "config": _VPN_STATE["config"],
        "ip":     _VPN_STATE["ip"],
        "log":    _VPN_STATE["log_tail"],
    }


# ── Download folder ───────────────────────────────────────────────────────────
@app.get("/downloads/list")
async def list_downloads(request: Request):
    if _AUTH_ENABLED:
        session = _get_session(request)
        if not session or not session.get("authenticated"):
            raise HTTPException(status_code=401, detail="Niet ingelogd")
    files = []
    for f in sorted(DOWNLOAD_DIR.iterdir()):
        if f.is_file():
            files.append({"name": f.name, "size": f.stat().st_size, "url": f"/downloads/{f.name}"})
    return JSONResponse(files)


@app.delete("/downloads/clear")
async def clear_downloads(request: Request):
    if _AUTH_ENABLED:
        session = _get_session(request)
        if not session or not session.get("authenticated"):
            raise HTTPException(status_code=401, detail="Niet ingelogd")
    count = 0
    for f in DOWNLOAD_DIR.iterdir():
        if f.is_file():
            f.unlink()
            count += 1
    return JSONResponse({"ok": True, "removed": count})


# ── Delete writeup ────────────────────────────────────────────────────────────
@app.delete("/writeups/{writeup_id}")
async def delete_writeup(writeup_id: int):
    try:
        r = requests.delete(
            f"{CTF_API_URL}/api/writeups/{writeup_id}",
            headers={"X-API-Key": CTF_API_KEY},
            timeout=10,
        )
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="Writeup niet gevonden")
        if r.status_code not in (200, 204):
            raise HTTPException(status_code=502, detail=f"CTF API fout: {r.text[:200]}")
        return JSONResponse({"ok": True})
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── AI hint ───────────────────────────────────────────────────────────────────
@app.post("/hint")
async def get_hint(request: Request):
    body       = await request.json()
    user_input = body.get("input", "").strip()
    history    = body.get("history", [])
    machine    = body.get("machine", "Onbekend")
    difficulty = body.get("difficulty", "Easy")
    platform   = body.get("platform", "HackTheBox")

    if not user_input:
        raise HTTPException(status_code=400, detail="Geen input opgegeven")

    system = f"""Je bent een senior ethical hacker en CTF-mentor. Je begeleidt een student door \
"{machine}" ({difficulty}) op {platform}.

JOUW ROL:
- Socratische methode: stel vragen, geef hints — geef NOOIT het volledige exploit-commando
- Reageer ALTIJD in het Nederlands
- Wees enthousiast en aanmoedigend
- Wijs op specifieke details in de output die de student moet onderzoeken
- Bouw voort op eerder genoemde bevindingen in de conversatiegeschiedenis

AFBEELDINGEN / DIAGRAMMEN:
- Als de student vraagt om een diagram, visueel overzicht of afbeelding: genereer een Mermaid-diagram
- Gebruik ```mermaid ... ``` blokken voor flowcharts, netwerktopologie of attack chains
- Voorbeeld Mermaid types: flowchart LR, sequenceDiagram, graph TD

ANTWOORDFORMAAT — retourneer ALTIJD geldig JSON:
{{
  "hint": "begeleiding in markdown — mag Mermaid-blokken bevatten voor diagrammen",
  "section": "Recon" | "Exploitation" | "Privilege Escalation" | "Lessons Learned",
  "snippet": "feitelijke markdown-samenvatting voor de writeup (leeg als nog niets concreets)"
}}

REGELS hint: één volgende stap als hint, **vet** voor sleutelbegrippen, nooit complete commando's.
REGELS snippet: alleen feiten, klaar voor de writeup, markdown met code blocks en tabellen."""

    messages = [{"role": "system", "content": system}]
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_input})

    loop = asyncio.get_event_loop()
    try:
        raw = await loop.run_in_executor(None, lambda: ai_complete(messages, max_tokens=1400))
        if raw.startswith("```json"):
            raw = raw[7:].rsplit("```", 1)[0].strip()
        elif raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        data.setdefault("hint", raw)
        data.setdefault("section", "Recon")
        data.setdefault("snippet", "")
    except json.JSONDecodeError:
        data = {"hint": raw, "section": "Recon", "snippet": ""}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI fout: {e}")

    return JSONResponse(data)


# ── WebSocket terminal (PTY) ──────────────────────────────────────────────────
@app.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    await websocket.accept()
    if _AUTH_ENABLED:
        token = websocket.cookies.get("_cs_session")
        valid = False
        if token:
            try:
                s = _signer.loads(token, max_age=28800)
                valid = bool(s.get("authenticated"))
            except Exception:
                pass
        if not valid:
            await websocket.send_text("\r\n\x1b[31m[Niet ingelogd — verbinding gesloten]\x1b[0m\r\n")
            await websocket.close(code=4001)
            return

    proc = ptyprocess.PtyProcess.spawn(
        ["/bin/bash", "-l"],
        cwd=str(Path.home()),
        dimensions=(24, 120),
    )

    loop = asyncio.get_event_loop()
    closed = asyncio.Event()

    async def pty_to_ws():
        """Stuur PTY-output naar de WebSocket."""
        while not closed.is_set() and proc.isalive():
            try:
                data = await loop.run_in_executor(None, _read_pty, proc)
                if data:
                    await websocket.send_bytes(data)
            except Exception:
                break
        closed.set()

    async def ws_to_pty():
        """Stuur WebSocket-input naar de PTY."""
        while not closed.is_set():
            try:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes"):
                    proc.write(msg["bytes"].decode("utf-8", errors="replace"))
                elif msg.get("text"):
                    try:
                        cmd = json.loads(msg["text"])
                        if cmd.get("type") == "resize":
                            proc.setwinsize(cmd["rows"], cmd["cols"])
                    except Exception:
                        proc.write(msg["text"])
            except WebSocketDisconnect:
                break
            except Exception:
                break
        closed.set()

    pty_task = asyncio.create_task(pty_to_ws())
    ws_task  = asyncio.create_task(ws_to_pty())
    await asyncio.wait([pty_task, ws_task], return_when=asyncio.FIRST_COMPLETED)

    pty_task.cancel()
    ws_task.cancel()
    try:
        proc.terminate(force=True)
    except Exception:
        pass


def _read_pty(proc: ptyprocess.PtyProcess) -> bytes:
    """Blokkerende PTY-read (wordt in executor gedraaid)."""
    try:
        return proc.read(4096)
    except Exception:
        return b""


# ── HTTP Terminal (SSE fallback voor WebSocket) ───────────────────────────────
import base64 as _base64

_pty_sessions: dict = {}  # sid -> {proc, queue}

def _pty_reader_thread(sid: str, proc, output_queue: queue.Queue):
    """Leest PTY output in aparte thread en plaatst in queue."""
    while proc.isalive():
        try:
            data = proc.read(4096)
            if data:
                output_queue.put(data)
        except Exception:
            break
    output_queue.put(None)  # sentinel: PTY gesloten
    _pty_sessions.pop(sid, None)


@app.post("/terminal/create")
async def terminal_create(request: Request):
    if _AUTH_ENABLED:
        session = _get_session(request)
        if not session or not session.get("authenticated"):
            raise HTTPException(status_code=401, detail="Niet ingelogd")
    sid = uuid.uuid4().hex[:16]
    env = os.environ.copy()
    env.update({
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
        "LANG": "en_US.UTF-8",
        "HOME": str(Path.home()),
        "USER": os.environ.get("USER", "stefan"),
        "SHELL": "/bin/bash",
    })
    proc = ptyprocess.PtyProcess.spawn(
        ["/bin/bash", "-l"],
        cwd=str(Path.home()),
        dimensions=(24, 120),
        env=env,
    )
    q: queue.Queue = queue.Queue(maxsize=2000)
    _pty_sessions[sid] = {"proc": proc, "queue": q}
    threading.Thread(target=_pty_reader_thread, args=(sid, proc, q), daemon=True).start()
    return JSONResponse({"session_id": sid})


@app.post("/terminal/input/{sid}")
async def terminal_input(sid: str, request: Request):
    if _AUTH_ENABLED:
        session = _get_session(request)
        if not session or not session.get("authenticated"):
            raise HTTPException(status_code=401, detail="Niet ingelogd")
    sess = _pty_sessions.get(sid)
    if not sess:
        raise HTTPException(status_code=404, detail="Sessie niet gevonden")
    body = await request.body()
    try:
        sess["proc"].write(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse({"ok": True})


@app.post("/terminal/resize/{sid}")
async def terminal_resize(sid: str, request: Request):
    if _AUTH_ENABLED:
        session = _get_session(request)
        if not session or not session.get("authenticated"):
            raise HTTPException(status_code=401, detail="Niet ingelogd")
    sess = _pty_sessions.get(sid)
    if not sess:
        return JSONResponse({"ok": False})
    body = await request.json()
    try:
        sess["proc"].setwinsize(int(body.get("rows", 24)), int(body.get("cols", 120)))
    except Exception:
        pass
    return JSONResponse({"ok": True})


@app.post("/terminal/poll/{sid}")
async def terminal_poll(sid: str, request: Request):
    """Long-poll: wacht op PTY-output en retourneer alles in één JSON-response.
    Werkt ook via proxies die SSE-streaming bufferen (bijv. WD NAS openresty)."""
    if _AUTH_ENABLED:
        session = _get_session(request)
        if not session or not session.get("authenticated"):
            raise HTTPException(status_code=401, detail="Niet ingelogd")
    sess = _pty_sessions.get(sid)
    if not sess:
        return JSONResponse({"closed": True, "data": ""})
    q = sess["queue"]
    loop = asyncio.get_event_loop()

    # Wacht maximaal 20 seconden op eerste datachunk
    try:
        first = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: q.get(timeout=20)),
            timeout=22,
        )
    except Exception:
        # Timeout — geen data, client poll opnieuw
        return JSONResponse({"closed": False, "data": ""})

    if first is None:
        return JSONResponse({"closed": True, "data": ""})

    # Verzamel aanvullende chunks die al klaarstaan (batch binnen 50ms)
    chunks = [first]
    deadline = loop.time() + 0.05
    while loop.time() < deadline:
        try:
            chunk = await loop.run_in_executor(None, q.get_nowait)
            if chunk is None:
                encoded = _base64.b64encode(b"".join(chunks)).decode("ascii")
                return JSONResponse({"closed": True, "data": encoded})
            chunks.append(chunk)
        except Exception:
            break

    encoded = _base64.b64encode(b"".join(chunks)).decode("ascii")
    return JSONResponse({"closed": False, "data": encoded})


@app.delete("/terminal/close/{sid}")
async def terminal_close(sid: str):
    sess = _pty_sessions.pop(sid, None)
    if sess:
        try:
            sess["proc"].terminate(force=True)
        except Exception:
            pass
    return JSONResponse({"ok": True})


# ── Terminal output analyse ───────────────────────────────────────────────────
@app.post("/analyze")
async def analyze_terminal(request: Request):
    """
    Analyseert gebufferde terminal-output en extraheert CTF-relevante bevindingen
    voor de writeup. Retourneert snippet="" als er niets relevants in zit.
    """
    body    = await request.json()
    output  = body.get("output", "").strip()
    machine = body.get("machine", "Onbekend")

    # Te kort om te analyseren
    if len(output) < 40:
        return JSONResponse({"relevant": False, "section": "Recon", "snippet": ""})

    system = f"""Je bent een CTF writeup-assistent voor machine "{machine}".
Analyseer de gegeven terminal-output en extraheer alleen feitelijke, CTF-relevante bevindingen.

Retourneer ALTIJD geldig JSON:
{{
  "relevant": true | false,
  "section": "Recon" | "Exploitation" | "Privilege Escalation" | "Lessons Learned",
  "snippet": "markdown samenvatting van de bevindingen (leeg als niet relevant)"
}}

RELEVANT = true bij:
- Open poorten, services, versienummers (nmap, netstat)
- HTTP-antwoorden, directories, bestanden (gobuster, ffuf, curl, wget)
- Credentials, wachtwoorden, tokens, API-keys
- sudo-rechten, SUID-bestanden, capabilities
- CVE-nummers, kwetsbare software
- Shell-toegang (whoami, id met interessante rechten)
- Interessante bestanden (config, .git, .env, backup, *.txt met data)
- Succesvolle exploits, reverse shells

RELEVANT = false bij:
- Alleen navigatie: cd, pwd, ls zonder interessante output, clear, echo zonder relevante waarde
- Lege output of alleen een prompt
- Command not found, permission denied (tenzij dit patroon zelf interessant is)
- Korte ping/connectivity-checks zonder bevindingen

REGELS snippet:
- Alleen feiten, geen hints of uitleg
- Gebruik markdown: tabellen voor poorten/services, code blocks voor commando's/output
- Beknopt maar compleet — wat gevonden, op welk pad/poort, welke versie"""

    prompt = f"Terminal output om te analyseren:\n```\n{output[:3000]}\n```"

    loop = asyncio.get_event_loop()
    try:
        raw = await loop.run_in_executor(None, lambda: ai_complete(
            [{"role": "system", "content": system},
             {"role": "user",   "content": prompt}],
            max_tokens=600,
        ))
        if raw.startswith("```json"):
            raw = raw[7:].rsplit("```", 1)[0].strip()
        elif raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        data.setdefault("relevant", False)
        data.setdefault("section",  "Recon")
        data.setdefault("snippet",  "")
    except Exception:
        return JSONResponse({"relevant": False, "section": "Recon", "snippet": ""})

    return JSONResponse(data)


# ── Writeup list ──────────────────────────────────────────────────────────────
@app.get("/writeups")
async def list_writeups():
    try:
        r = requests.get(
            f"{CTF_API_URL}/api/writeups",
            headers={"X-API-Key": CTF_API_KEY},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return []


# ── Progress (streak / XP) ────────────────────────────────────────────────────
PROGRESS_FILE = Path(__file__).parent / "progress.json"

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"xp": 0, "streak": 0, "last_played": None, "cards_done": 0}

def save_progress(data: dict):
    PROGRESS_FILE.write_text(json.dumps(data))

@app.get("/api/progress")
async def get_progress():
    return load_progress()

@app.post("/api/progress")
async def update_progress(request: Request):
    from datetime import timedelta
    body     = await request.json()
    progress = load_progress()
    today    = datetime.now().date().isoformat()
    last     = progress.get("last_played")
    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()

    if last == today:
        pass  # al gespeeld vandaag
    elif last == yesterday:
        progress["streak"] = progress.get("streak", 0) + 1
    else:
        progress["streak"] = 1  # reset of eerste keer

    progress["last_played"]  = today
    progress["xp"]           = progress.get("xp", 0) + body.get("xp", 0)
    progress["cards_done"]   = progress.get("cards_done", 0) + body.get("cards", 0)
    save_progress(progress)
    return progress


CARD_SYSTEM = """Genereer 10 diverse leerkaarten voor een CTF-student op basis van de writeup.

Retourneer ALLEEN een JSON-array:
[
  {
    "type": "command" | "concept" | "scenario" | "term",
    "question": "de vraag (Nederlands)",
    "answer": "het volledige antwoord (Nederlands, mag markdown)",
    "hint": "optionele kleine hint",
    "category": "Recon" | "Exploitation" | "Privilege Escalation" | "Tools"
  }
]

Kaarttypen (maak ze divers):
- command  : toon een commando-fragment → vraag wat het doet / waarom
- concept  : leg een aanvalstechniek uit → vraag de naam of wat het is
- scenario : beschrijf een situatie → vraag welke stap je zet (open vraag)
- term     : geef een technische term → vraag definitie + praktijktoepassing

Schrijf altijd in het Nederlands. Maak het praktisch en direct toepasbaar."""


async def _gen_one_machine(src: dict, loop) -> list:
    """Genereert kaarten voor één writeup. Retourneert lege lijst bij fout."""
    msgs = [
        {"role": "system", "content": CARD_SYSTEM},
        {"role": "user",   "content": f"Writeup van {src['machine']}:\n{src['writeup'][:3500]}"},
    ]
    try:
        raw = await loop.run_in_executor(None, lambda m=msgs: ai_complete(m, max_tokens=2000))
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        cards = json.loads(raw)
        for card in cards:
            card["machine"] = src["machine"]
            card["id"]      = uuid.uuid4().hex[:8]
        return cards
    except Exception:
        return []


async def _generate_cards_bg():
    """Genereert kaarten voor alle writeups parallel en slaat ze direct op zodra de eerste klaar is."""
    import random
    global _card_cache
    loop = asyncio.get_event_loop()

    def _fetch():
        try:
            r = requests.get(f"{CTF_API_URL}/api/writeups",
                             headers={"X-API-Key": CTF_API_KEY}, timeout=10)
            return r.json()
        except Exception:
            return []

    writeups = await loop.run_in_executor(None, _fetch)
    if not writeups:
        return

    # Start alle machines parallel — zodra één klaar is, update de cache al
    tasks = [asyncio.create_task(_gen_one_machine(src, loop)) for src in writeups]
    accumulated = list(_card_cache)  # Bewaar huidige cache

    for coro in asyncio.as_completed(tasks):
        new_cards = await coro
        if new_cards:
            accumulated.extend(new_cards)
            random.shuffle(accumulated)
            _card_cache = list(accumulated)
            _save_card_cache(accumulated)


@app.on_event("startup")
async def startup_event():
    global _card_cache
    _card_cache = _load_card_cache()
    # Pre-genereer kaarten op achtergrond als cache leeg is
    if not _card_cache:
        asyncio.create_task(_generate_cards_bg())


# ── Card generation ───────────────────────────────────────────────────────────
@app.get("/api/cards")
async def get_cards(machine: str = "", refresh: bool = False):
    """Geeft leerkaarten terug — uit cache (instant) of genereert vers als cache leeg is."""
    import random
    global _card_cache

    # Gefilterd op machine
    if machine and _card_cache:
        filtered = [c for c in _card_cache if c.get("machine", "").lower() == machine.lower()]
        if filtered:
            return JSONResponse(filtered)

    # Cache beschikbaar en geen refresh gevraagd
    if _card_cache and not refresh:
        deck = random.sample(_card_cache, min(15, len(_card_cache)))
        return JSONResponse(deck)

    # Cache leeg of refresh: genereer verse kaarten
    async with _card_generation_lock:
        # Check nogmaals na lock (concurrent request kan al gevuld hebben)
        if _card_cache and not refresh:
            return JSONResponse(random.sample(_card_cache, min(15, len(_card_cache))))

        asyncio.create_task(_generate_cards_bg())
        # Geef tijdelijk een wacht-kaart terug als er echt niets is
        if not _card_cache:
            return JSONResponse([])
        return JSONResponse(random.sample(_card_cache, min(15, len(_card_cache))))


@app.post("/api/cards/refresh")
async def refresh_cards():
    """Triggert hernieuwde kaartgeneratie op de achtergrond."""
    asyncio.create_task(_generate_cards_bg())
    return {"status": "generating"}


# ── PWA assets ────────────────────────────────────────────────────────────────
@app.get("/manifest.json")
async def manifest():
    return JSONResponse({
        "name":             "CTF Learn",
        "short_name":       "CTF Learn",
        "description":      "Leer ethical hacking via swipe-kaarten",
        "start_url":        "/learn",
        "display":          "standalone",
        "background_color": "#0d1117",
        "theme_color":      "#58a6ff",
        "orientation":      "portrait",
        "icons": [
            {"src": "/icon.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon.png", "sizes": "512x512", "type": "image/png"},
        ],
    })

@app.get("/sw.js")
async def service_worker():
    from fastapi.responses import Response
    sw = """
const CACHE = 'ctf-learn-v1';
const ASSETS = ['/learn', '/manifest.json'];

self.addEventListener('install', e =>
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)))
);

self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) return;
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request).then(res => {
      const clone = res.clone();
      caches.open(CACHE).then(c => c.put(e.request, clone));
      return res;
    }))
  );
});
"""
    return Response(content=sw, media_type="application/javascript")


# ── Serve editor & learn ──────────────────────────────────────────────────────
@app.get("/learn", response_class=HTMLResponse)
async def learn():
    html_path = Path(__file__).parent / "learn.html"
    return html_path.read_text(encoding="utf-8")

@app.get("/", response_class=HTMLResponse)
async def editor(request: Request):
    html_path = Path(__file__).parent / "editor.html"
    html = html_path.read_text(encoding="utf-8")
    # Detect correct WebSocket scheme via proxy headers
    fwd_scheme = request.headers.get("x-forwarded-scheme") or request.headers.get("x-forwarded-proto", "")
    ws_proto = "wss" if fwd_scheme.lower() == "https" else "ws"
    html = html.replace(
        "const proto = location.protocol === 'https:' ? 'wss' : 'ws';",
        f"const proto = '{ws_proto}';  // injected by server"
    )
    return html


# ── Auth routes ───────────────────────────────────────────────────────────────
def _login_html(error: str = "") -> str:
    err_block = f'<p class="err">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Inloggen — cyberstefan.nl</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
  <style>
    :root {{ --bg:#0d1117; --surface:#161b22; --border:#30363d; --text:#e6edf3; --muted:#8b949e; --accent:#58a6ff; --red:#f85149; }}
    *,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{ background:var(--bg); color:var(--text); font-family:'Inter',sans-serif; min-height:100vh; display:flex; align-items:center; justify-content:center; }}
    .box {{ width:100%; max-width:360px; padding:40px 32px; background:var(--surface); border:1px solid var(--border); border-radius:12px; }}
    .logo {{ display:flex; align-items:center; gap:10px; margin-bottom:28px; }}
    .logo svg {{ color:var(--accent); }}
    .logo span {{ font-family:'JetBrains Mono',monospace; font-size:1rem; font-weight:500; color:var(--text); }}
    h1 {{ font-size:0.7rem; text-transform:uppercase; letter-spacing:0.1em; color:var(--muted); margin-bottom:24px; }}
    label {{ display:block; font-size:0.78rem; color:var(--muted); margin-bottom:5px; }}
    input {{ width:100%; background:var(--bg); border:1px solid var(--border); color:var(--text); padding:9px 12px; border-radius:6px; font-size:0.88rem; outline:none; margin-bottom:16px; transition:border-color .15s; }}
    input:focus {{ border-color:var(--accent); }}
    button {{ width:100%; padding:10px; background:var(--accent); color:#0d1117; border:none; border-radius:6px; font-size:0.9rem; font-weight:600; cursor:pointer; margin-top:4px; transition:opacity .15s; }}
    button:hover {{ opacity:0.88; }}
    .err {{ color:var(--red); font-size:0.82rem; margin-bottom:16px; padding:10px 12px; border:1px solid rgba(248,81,73,.3); border-radius:6px; background:rgba(248,81,73,.06); }}
    .duo-note {{ margin-top:20px; font-size:0.75rem; color:var(--muted); text-align:center; display:flex; align-items:center; justify-content:center; gap:6px; }}
  </style>
</head>
<body>
  <div class="box">
    <div class="logo">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2"/><path d="m8 21 4-4 4 4"/><path d="M7 7h.01"/><path d="M11 7h6"/><path d="M7 11h.01"/><path d="M11 11h6"/>
      </svg>
      <span>cyberstefan.nl</span>
    </div>
    <h1>Toegang vereist</h1>
    {err_block}
    <form method="post" action="/login">
      <label for="u">Gebruikersnaam</label>
      <input id="u" name="username" type="text" autocomplete="username" required autofocus>
      <label for="p">Wachtwoord</label>
      <input id="p" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Inloggen</button>
    </form>

  </div>
</body>
</html>"""


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _get_session(request) and _get_session(request).get("authenticated"):
        return RedirectResponse(url="/", status_code=302)
    return HTMLResponse(_login_html())


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    pw_hash  = hashlib.sha256(password.encode()).hexdigest()

    if username != _ADMIN_USER or pw_hash != _ADMIN_PW_HASH:
        return HTMLResponse(_login_html("Ongeldige gebruikersnaam of wachtwoord"), status_code=401)

    if _DUO_ENABLED:
        client = _make_duo_client()
        state  = client.generate_state()
        pending_token = _signer.dumps({"username": username, "duo_state": state})
        response = RedirectResponse(url=client.create_auth_url(username, state), status_code=303)
        response.set_cookie("_cs_pending", pending_token, httponly=True, samesite="lax", max_age=300)
        return response

    # Duo niet geconfigureerd — alleen wachtwoord
    token    = _signer.dumps({"authenticated": True, "username": username})
    response = RedirectResponse(url="/learning", status_code=303)
    response.set_cookie("_cs_session", token, httponly=True, samesite="lax", max_age=28800)
    return response


@app.get("/auth/duo/callback")
async def duo_callback(request: Request, duo_code: str = "", state: str = ""):
    pending_token = request.cookies.get("_cs_pending")
    if not pending_token or not duo_code or not state:
        return RedirectResponse("/login")
    try:
        pending = _signer.loads(pending_token, max_age=300)
    except Exception:
        return RedirectResponse("/login")
    if state != pending.get("duo_state"):
        return HTMLResponse(_login_html("Ongeldige sessiestatus — probeer opnieuw"), status_code=403)

    client = _make_duo_client()
    try:
        client.exchange_authorization_code_for_2fa_result(duo_code, pending["username"])
    except Exception:
        return HTMLResponse(_login_html("Duo authenticatie mislukt of geannuleerd"))

    token    = _signer.dumps({"authenticated": True, "username": pending["username"]})
    response = RedirectResponse(url="/learning", status_code=303)
    response.set_cookie("_cs_session", token, httponly=True, samesite="lax", max_age=28800)
    response.delete_cookie("_cs_pending")
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("_cs_session")
    return response
