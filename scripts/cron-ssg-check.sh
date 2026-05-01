#!/bin/bash
# Safety-net: herbouw statische pagina's als de DB nieuwer is dan de homepage.
# Toevoegen via: crontab -e
#   */5 * * * * /home/stefan/ctf-workflow/scripts/cron-ssg-check.sh
#
# Dit vangt directe DB-schrijfoperaties op die de API-hook omzeilen
# (bijv. sqlite3 op de CLI, Claude Code die direct in de DB schrijft).

DB="/home/stefan/ctf-workflow/api/writeups.db"
INDEX="/home/stefan/ctf-workflow/web/index.html"
SSG="/home/stefan/ctf-workflow/ssg.py"

# Herbouw alleen als DB gewijzigd is na de laatste homepage-generatie
if [ "$DB" -nt "$INDEX" ]; then
    python3 "$SSG" >> /var/log/cyberstefan-ssg.log 2>&1
fi
