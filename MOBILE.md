# Mobiele workflow — CyberStefan

## Hoe werkt het

Wijzigingen vanuit de Claude-app op je telefoon gaan direct naar de `main` branch. De auto-commit hook pakt lokale wijzigingen op; voor mobiele edits commit Claude zelf via de GitHub-connector.

```
Claude-app (mobiel)
    ↓  schrijft via GitHub-connector
GitHub main branch
    ↓  auto-sync naar server
cyberstefan.nl live
```

---

## Eenmalige setup — GitHub-connector in Claude-app

1. Open **Claude.ai** op je telefoon
2. Ga naar **Settings → Integrations → GitHub**
3. Koppel je GitHub-account (`stiflerstef-dev`)
4. Geef toegang tot repo **`stiflerstef-dev/cyberstefan-nl`**

Daarna kan Claude in de app bestanden lezen én schrijven in de repo.

---

## Mobiel editen — voorbeelden

### Nieuwe writeup aanmaken

Zeg tegen Claude:
> "Maak een nieuwe writeup-pagina aan voor machine `knife` (ID 5, Easy, HackTheBox). Gebruik het slug-template."

Claude maakt aan:
- `web/writeup/knife/index.html`
- Voegt URL toe aan `web/sitemap.xml`
- Commit direct op `main`

### Bestaande pagina aanpassen

> "Pas de meta-description van `/writeup/sau/` aan naar: '…'"

Claude leest het bestand, past het aan, commit.

### Index bijwerken (nieuwe writeup-kaart)

> "Voeg een kaart toe voor machine `knife` (Easy, HackTheBox, tags: LDAP, Kerberos) aan `web/index.html`."

---

## Vanuit Claude Code CLI werken

```bash
# Pull laatste wijzigingen van mobiel
git pull origin main

# Wijzigingen pushen zodat je ze mobiel ziet
git add web/ api/ nginx-cyberstefan.conf
git commit -m "beschrijving"
git push origin main
```

De auto-commit hook doet dit automatisch bij elke bestandswijziging.

---

## Dashboard

URL: **https://cyberstefan.nl/dashboard**

Login via Duo (zelfde als `/learning`). Toont:
- Pageviews vandaag / 30 dagen / all-time
- Sparkline grafiek afgelopen 30 dagen
- Top 10 pagina's
- Alle writeups met moeilijkheidsgraad

---

## Structuur van de repo

```
web/
  index.html          — homepage (hardcoded kaarten)
  sitemap.xml         — bijwerken bij elke nieuwe writeup
  writeup/{slug}/     — één map per machine
    index.html        — hardcoded meta + window._WRITEUP_ID
  resources/
    index.html
api/
  main.py             — FastAPI CTF-writeups backend
  writeups.db         — SQLite (niet in git)
nginx-cyberstefan.conf — nginx referentieconfig
```

---

## Regels

- **Nooit** `api/writeups.db` committen (staat in .gitignore)
- **Nooit** `.env` bestanden committen
- Bij nieuwe writeup altijd ook `web/sitemap.xml` bijwerken
- Slug altijd lowercase, geen spaties: `knife`, `active`, `forest`
