# Busqueda — Raw Notes (HTB, Easy)

## Recon
- nmap: poorten 22 (SSH, OpenSSH 8.9p1 Ubuntu) en 80 (HTTP, Apache 2.4.52) open
- Server host: searcher.htb, redirect naar http://searcher.htb/
- Website footer: app draait op Flask + Searchor 2.4.0
- Searchor 2.4.0 is kwetsbaar voor Python code-injectie via eval() in het engine-parameter

## Foothold — Python code injection (Searchor 2.4.0)
- Searchor 2.4.0 verwerkt zoekopdrachten met eval()
- Door een kwaadaardige waarde in het engine-parameter te injecteren, kunnen willekeurige Python-commando's worden uitgevoerd
- Payload via Burp Suite: engine-parameter bevat Python reverse shell via socket en subprocess
- Server reageert HTTP 200, browser redirect naar AccuWeather — bevestigt dat eval() de payload uitvoert
- Reverse shell ontvangen op netcat poort 13337, shell als gebruiker 'svc' in /var/www/app

## Enumeration
- Credentials in .git/config: remote URL bevat plaintext creds: cody:jh1usoih2bkjaspwe92@gitea.searcher.htb
- Gitea draait intern op gitea.searcher.htb:3000 (versie 1.18.0+rc1)
- Gitea accounts: administrator en cody. Wachtwoord van cody werkt ook voor administrator-account
- sudo -l: svc mag /usr/bin/python3 /opt/scripts/system-checkup.py * uitvoeren als root (NOPASSWD)
- system-checkup.py broncode niet leesbaar via cat (permission denied)

## Privilege Escalation
- system-checkup.py biedt drie opties: docker-ps, docker-inspect, full-checkup
- docker-ps: twee draaiende containers — gitea (poort 3000) en mysql_db (poort 3306)
- docker-inspect '{{json .}}' gitea | jq lekt omgevingsvariabelen inclusief GITEA__database__PASSWD=yuiu1hoiu4i5ho1uh
- Wachtwoord geeft toegang tot Gitea administrator-account en private repository met system-checkup.py broncode
- system-checkup.py full-checkup voert ./full-checkup.sh uit relatief aan de huidige map (geen absoluut pad)
- Aanval: schrijf kwaadaardig full-checkup.sh in een schrijfbare map (bijv. /tmp), geef uitvoerrechten, voer sudo system-checkup.py full-checkup uit vanuit die map
- Resultaat: root shell

## Tools gebruikt
- nmap, Burp Suite, netcat, Python reverse shell, jq, docker inspect
