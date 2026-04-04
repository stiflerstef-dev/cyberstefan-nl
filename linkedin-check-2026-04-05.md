# LinkedIn check — 2026-04-05

Controleer of de LinkedIn API weer werkt. Als niet: verwijder LinkedIn uit de workflow.

## Commando om token te testen:
```bash
LINKEDIN_TOKEN=$(sudo cat /etc/ctf-workflow.env | grep "^LINKEDIN_ACCESS_TOKEN=" | cut -d= -f2-)
curl -s -H "Authorization: Bearer $LINKEDIN_TOKEN" -H "X-Restli-Protocol-Version: 2.0.0" https://api.linkedin.com/v2/userinfo
```

## Als het WEL werkt (HTTP 200):
Post de Cap LinkedIn post alsnog:
```bash
LINKEDIN_TOKEN=$(sudo cat /etc/ctf-workflow.env | grep "^LINKEDIN_ACCESS_TOKEN=" | cut -d= -f2-)
LINKEDIN_ACCESS_TOKEN="$LINKEDIN_TOKEN" python3 /tmp/cap-full-workflow.py
```

## Als het NIET werkt:
Verwijder LinkedIn uit de workflow — vertel Claude: "De LinkedIn API werkt nog steeds niet, verwijder LinkedIn uit cyberstefan.nl en de workflow."
