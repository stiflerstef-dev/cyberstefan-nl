#!/usr/bin/env python3
"""
CTF Telegram Bot
- Beantwoordt vragen over CTF challenges (tekst + screenshots)
- Analyseer screenshots via Claude Vision
- /addnotes <tekst> — voegt notities toe aan lopende sessie
- /writeup — stuurt huidige sessie-notities als writeup naar de website
- Alleen toegankelijk voor de geconfigureerde TELEGRAM_CHAT_ID
"""

import base64
import json
import logging
import os
import tempfile
from collections import deque
from datetime import datetime
from pathlib import Path

from openai import OpenAI
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ["TELEGRAM_CTF_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])
OPENROUTER_KEY  = os.environ["OPENROUTER_API_KEY"]
CTF_API_URL     = os.environ.get("CTF_API_URL", "http://127.0.0.1:8000")
CTF_API_KEY     = os.environ.get("CTF_API_KEY", "")

WORKFLOW_DIR    = Path.home() / "ctf-workflow"
SESSION_FILE    = WORKFLOW_DIR / ".bot_session.json"

AI_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
ai = OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

SYSTEM_PROMPT = """Je bent een ervaren CTF-speler en penetration tester die helpt bij HackTheBox en TryHackMe challenges. Je praat met Stefan, jouw enige gebruiker.

Gedraag je als een directe collega, niet als een assistent:
- Praat normaal en ontspannen — geen bullet points tenzij het echt helpt
- Geef hints en duw in de goede richting, maar geef niet meteen de volledige oplossing tenzij Stefan dat expliciet vraagt
- Als je een screenshot krijgt: beschrijf wat je ziet en geef concrete volgende stappen
- Antwoord in dezelfde taal als Stefan (NL of EN, wissel mee)
- Onthoud wat eerder in het gesprek is gezegd en verwijs daar naar als het relevant is
- Als Stefan iets vertelt over zijn voortgang, reageer daar op zoals een collega zou doen"""

# Conversatiegeschiedenis — max 40 berichten (20 heen-en-weer) bewaard in geheugen
HISTORY: deque = deque(maxlen=40)

# ── Session state (simpele JSON op disk) ─────────────────────────────────────────
def load_session() -> dict:
    if SESSION_FILE.exists():
        return json.loads(SESSION_FILE.read_text())
    return {"machine": None, "difficulty": None, "platform": None, "notes": [], "started": None}

def save_session(session: dict):
    SESSION_FILE.write_text(json.dumps(session, indent=2))

def reset_session():
    SESSION_FILE.write_text(json.dumps(
        {"machine": None, "difficulty": None, "platform": None, "notes": [], "started": None},
        indent=2
    ))

# ── Auth check ───────────────────────────────────────────────────────────────────
def is_allowed(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID

async def deny(update: Update):
    await update.message.reply_text("Unauthorized.")

# ── Handlers ─────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    session = load_session()
    machine_info = f"*{session['machine']}* ({session['difficulty']}, {session['platform']})" \
        if session.get("machine") else "geen actieve sessie"

    await update.message.reply_text(
        f"*CTF Bot actief*\n\n"
        f"Huidige sessie: {machine_info}\n\n"
        f"Stuur gewoon een bericht — ik onthoud de context van ons gesprek.\n"
        f"Stuur een screenshot en ik analyseer het.\n\n"
        f"*Sessie commando's:*\n"
        f"`/session <machine> <difficulty> <platform>` — start sessie\n"
        f"`/addnotes <tekst>` — voeg notitie toe\n"
        f"`/notes` — bekijk notities\n"
        f"`/writeup` — push writeup naar cyberstefan.nl\n"
        f"`/clear` — wis gespreksgeheugen\n"
        f"`/reset` — reset alles",
        parse_mode="Markdown"
    )

async def cmd_session(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    args = ctx.args
    if len(args) < 3:
        await update.message.reply_text(
            "Gebruik: `/session <machine> <Easy|Medium|Hard|Insane> <HackTheBox|TryHackMe|Other>`",
            parse_mode="Markdown"
        )
        return

    machine    = args[0]
    difficulty = args[1].capitalize()
    platform   = args[2]

    platform_map = {"htb": "HackTheBox", "thm": "TryHackMe"}
    platform = platform_map.get(platform.lower(), platform)

    if difficulty not in ("Easy", "Medium", "Hard", "Insane"):
        await update.message.reply_text("Difficulty moet Easy, Medium, Hard of Insane zijn.")
        return

    session = {"machine": machine, "difficulty": difficulty, "platform": platform,
               "notes": [], "started": datetime.now().isoformat()}
    save_session(session)
    await update.message.reply_text(
        f"Sessie gestart: *{machine}* — {difficulty} — {platform}",
        parse_mode="Markdown"
    )

async def cmd_addnotes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    if not ctx.args:
        await update.message.reply_text("Gebruik: `/addnotes <tekst>`", parse_mode="Markdown")
        return
    note = " ".join(ctx.args)
    session = load_session()
    session["notes"].append(f"[{datetime.now().strftime('%H:%M')}] {note}")
    save_session(session)
    await update.message.reply_text(f"Notitie toegevoegd ({len(session['notes'])} totaal).")

async def cmd_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    session = load_session()
    if not session["notes"]:
        await update.message.reply_text("Geen notities in deze sessie.")
        return
    notes_text = "\n".join(f"• {n}" for n in session["notes"])
    await update.message.reply_text(
        f"*Notities voor {session.get('machine', '?')}:*\n\n{notes_text}",
        parse_mode="Markdown"
    )

async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    reset_session()
    HISTORY.clear()
    await update.message.reply_text("Sessie en gespreksgeschiedenis gereset.")

async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    HISTORY.clear()
    await update.message.reply_text("Gespreksgeheugen gewist — sessie blijft actief.")

async def cmd_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Trigger media generatie voor de laatste writeup op de site."""
    if not is_allowed(update): return await deny(update)
    if not CTF_API_KEY:
        await update.message.reply_text("CTF_API_KEY niet ingesteld.")
        return
    try:
        # Haal de laatste writeup op
        r = requests.get(f"{CTF_API_URL}/api/writeups", timeout=5)
        writeups = r.json()
        if not writeups:
            await update.message.reply_text("Geen writeups gevonden op de site.")
            return
        latest = writeups[0]
        wid = latest["id"]

        # Check of media al bestaat
        m = requests.get(f"{CTF_API_URL}/api/writeups/{wid}/media", timeout=5).json()
        if m.get("status") == "ready":
            await update.message.reply_text(
                f"Media voor *{esc(latest['machine'])}* bestaat al.\n"
                f"Gebruik `/media regenerate` om te hergeneren.",
                parse_mode="Markdown"
            )
            return

        # Trigger generatie
        requests.post(
            f"{CTF_API_URL}/api/writeups/{wid}/media",
            headers={"X-API-Key": CTF_API_KEY},
            timeout=5
        )
        await update.message.reply_text(
            f"Media voor *{esc(latest['machine'])}* wordt gegenereerd...\n"
            f"Podcast + slides verschijnen automatisch op de writeup pagina.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Fout: {e}")

def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

async def cmd_writeup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    session = load_session()

    if not session.get("machine"):
        await update.message.reply_text(
            "Geen actieve sessie. Start er een met `/session <machine> <difficulty> <platform>`.",
            parse_mode="Markdown"
        )
        return

    # Bron 1: handmatige notities via /addnotes
    manual_notes = "\n".join(session["notes"])

    # Bron 2: gespreksgeschiedenis (alleen user-berichten, geen bot-antwoorden)
    conversation_log = "\n".join(
        f"Stefan: {m['content']}" if isinstance(m['content'], str) else f"Stefan: [screenshot]"
        for m in HISTORY
        if m["role"] == "user"
    )

    if not manual_notes and not conversation_log:
        await update.message.reply_text("Geen notities of gespreksgeschiedenis om writeup van te maken.")
        return

    raw_notes = ""
    if manual_notes:
        raw_notes += f"=== Notities ===\n{manual_notes}\n\n"
    if conversation_log:
        raw_notes += f"=== Gesprekslog ===\n{conversation_log}"

    await update.message.reply_text("Writeup genereren via Claude... even wachten.")

    # Claude: formateer writeup
    VALID_TAGS = ["SQLi", "RCE", "Buffer Overflow", "LFI", "SSRF",
                  "XSS", "Privesc", "Enumeration", "Web", "Linux"]
    try:
        wmodel_resp = ai.chat.completions.create(
            model=AI_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": f"""
Zet deze CTF notities om naar een gestructureerde writeup voor "{session['machine']}"
({session['difficulty']}) op {session['platform']}.

Gebruik deze secties: ## Recon, ## Exploitation, ## Privilege Escalation, ## Lessons Learned

Eindig met een JSON blok (```json) met tags uit: {VALID_TAGS}
Formaat: {{"tags": ["tag1", "tag2"]}}

Notities:
{raw_notes}
"""}],
        )
        full = wmodel_resp.choices[0].message.content
        tags = []
        if "```json" in full:
            try:
                tags = json.loads(full.split("```json")[1].split("```")[0].strip()).get("tags", [])
                tags = [t for t in tags if t in VALID_TAGS]
            except Exception:
                pass
            full = full.split("```json")[0].strip()
        writeup = full

        # Claude: LinkedIn post
        li_resp = wmodel.generate_content(f"""
Schrijf een korte LinkedIn post (max 200 woorden) over het oplossen van
"{session['machine']}" ({session['difficulty']}) op {session['platform']}.
Focus op het leerproces, geen jargon. Eindig met 3-5 hashtags.
Geen corporate speak. Persoonlijk en authentiek.

Writeup:
{writeup[:1000]}
""")
        linkedin = li_resp.text.strip()

        # Push naar website API
        if CTF_API_KEY:
            api_resp = requests.post(
                f"{CTF_API_URL}/api/writeups",
                headers={"X-API-Key": CTF_API_KEY},
                json={
                    "machine": session["machine"],
                    "difficulty": session["difficulty"],
                    "platform": session["platform"],
                    "tags": tags,
                    "writeup": writeup,
                    "linkedin": linkedin,
                    "status": "Completed",
                },
                timeout=10,
            )
            if api_resp.status_code in (200, 201):
                wid = api_resp.json()["id"]
                url = f"https://cyberstefan.nl/writeup/{wid}"
                await update.message.reply_text(
                    f"Writeup gepubliceerd!\n{url}\n\n*LinkedIn post:*\n{linkedin}",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(f"API fout: {api_resp.status_code}\n\n{writeup[:500]}")
        else:
            await update.message.reply_text(f"*Writeup klaar (niet gepusht — geen API key):*\n\n{writeup[:1000]}", parse_mode="Markdown")

        reset_session()

    except Exception as e:
        log.exception("Writeup generation failed")
        await update.message.reply_text(f"Fout: {e}")

# ── Helpers ───────────────────────────────────────────────────────────────────────
def build_system() -> str:
    session = load_session()
    if session.get("machine"):
        return (SYSTEM_PROMPT +
                f"\n\nActieve CTF sessie: {session['machine']} "
                f"({session['difficulty']}, {session['platform']}). "
                f"Houd hier rekening mee in je antwoorden.")
    return SYSTEM_PROMPT

async def send_reply(update: Update, answer: str):
    """Stuur antwoord; val terug op plain text als Markdown parse mislukt."""
    if len(answer) > 4000:
        answer = answer[:4000] + "\n\n_(ingekort)_"
    try:
        await update.message.reply_text(answer, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(answer)

# ── Tekstvraag ────────────────────────────────────────────────────────────────────

WRITEUP_TRIGGERS = [
    "maak een writeup", "genereer een writeup", "writeup maken",
    "make a writeup", "generate writeup", "create writeup",
    "publiceer", "publish writeup",
]

NOTE_TRIGGERS = [
    "sla dit op", "noteer dit", "voeg dit toe aan", "add this to",
    "save this", "onthoud dit voor de writeup",
]

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)

    user_text = update.message.text
    lower = user_text.lower()

    # Natuurlijke writeup-trigger
    if any(t in lower for t in WRITEUP_TRIGGERS):
        await cmd_writeup(update, ctx)
        return

    # Natuurlijke "sla op als notitie"-trigger
    if any(t in lower for t in NOTE_TRIGGERS):
        session = load_session()
        note = user_text
        session["notes"].append(f"[{datetime.now().strftime('%H:%M')}] {note}")
        save_session(session)
        HISTORY.append({"role": "user", "content": user_text})
        HISTORY.append({"role": "assistant", "content": "Opgeslagen als notitie voor de writeup."})
        await update.message.reply_text("Opgeslagen als notitie voor de writeup.")
        return

    HISTORY.append({"role": "user", "content": user_text})

    try:
        messages = [{"role": "system", "content": build_system()}] + list(HISTORY)
        resp = ai.chat.completions.create(model=AI_MODEL, messages=messages, max_tokens=1024)
        answer = resp.choices[0].message.content
        HISTORY.append({"role": "assistant", "content": answer})
        await send_reply(update, answer)
    except Exception as e:
        log.exception("Text handler failed")
        await update.message.reply_text(f"Fout: {e}")

# ── Screenshot / foto ─────────────────────────────────────────────────────────────
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)

    caption = update.message.caption or "Wat zie je hier? Analyseer en geef me de volgende stap."

    try:
        photo = update.message.photo[-1]
        tg_file = await ctx.bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await tg_file.download_to_drive(tmp.name)
            image_data = base64.standard_b64encode(Path(tmp.name).read_bytes()).decode()
        Path(tmp.name).unlink(missing_ok=True)

        # Bouw berichten op: geschiedenis + dit nieuwe bericht met afbeelding
        image_message = {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data},
                },
                {"type": "text", "text": caption},
            ],
        }
        messages = list(HISTORY) + [image_message]

        resp = ai.chat.completions.create(
            model=AI_MODEL,
            max_tokens=1024,
            messages=list(HISTORY) + [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                    {"type": "text", "text": caption},
                ],
            }],
        )
        answer = resp.choices[0].message.content

        # Sla op in geschiedenis als tekstrepresentatie (geen base64 bewaren)
        HISTORY.append({"role": "user", "content": f"[screenshot] {caption}"})
        HISTORY.append({"role": "assistant", "content": answer})

        await send_reply(update, answer)

    except Exception as e:
        log.exception("Photo handler failed")
        await update.message.reply_text(f"Fout bij analyseren: {e}")

# ── Document (bijv. groot screenshot als bestand) ─────────────────────────────────
async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)

    doc = update.message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await update.message.reply_text("Stuur afbeeldingen als foto of als image-bestand.")
        return

    # Behandel hetzelfde als foto maar met document file_id
    update.message.photo = [doc]  # type: ignore
    await handle_photo(update, ctx)

# ── Main ──────────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("session",  cmd_session))
    app.add_handler(CommandHandler("addnotes", cmd_addnotes))
    app.add_handler(CommandHandler("notes",    cmd_notes))
    app.add_handler(CommandHandler("writeup",  cmd_writeup))
    app.add_handler(CommandHandler("reset",    cmd_reset))
    app.add_handler(CommandHandler("clear",    cmd_clear))
    app.add_handler(CommandHandler("media",    cmd_media))
    app.add_handler(MessageHandler(filters.PHOTO,      handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("CTF Bot gestart — polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
