#!/usr/bin/env bash
# Configureert nginx met self-signed SSL voor lokaal gebruik op cyberstefan.nl
set -euo pipefail

DOMAIN="cyberstefan.nl"
WORKFLOW_DIR="/home/stefan/ctf-workflow"
NGINX_CONF="/etc/nginx/sites-available/${DOMAIN}"
SSL_DIR="/etc/ssl/cyberstefan"

echo "── Nginx + Self-Signed SSL voor ${DOMAIN} ──────────────"

# ── 1. nginx installeren ─────────────────────────────────────────────────────────
if ! command -v nginx &>/dev/null; then
    echo "[1/4] nginx installeren..."
    apt-get update -qq && apt-get install -y nginx
else
    echo "[1/4] nginx aanwezig ($(nginx -v 2>&1))"
fi

# ── 2. Self-signed certificaat genereren ─────────────────────────────────────────
echo "[2/4] Self-signed certificaat genereren..."
mkdir -p "$SSL_DIR"

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "$SSL_DIR/key.pem" \
    -out    "$SSL_DIR/cert.pem" \
    -subj   "/CN=${DOMAIN}/O=CyberStefan/C=NL" \
    -addext "subjectAltName=DNS:${DOMAIN},DNS:www.${DOMAIN},IP:192.168.2.112" \
    2>/dev/null

chmod 600 "$SSL_DIR/key.pem"
echo "       Certificaat: $SSL_DIR/cert.pem (geldig 10 jaar)"

# ── 3. nginx config activeren ────────────────────────────────────────────────────
echo "[3/4] nginx configureren..."
cp "$WORKFLOW_DIR/nginx-cyberstefan.conf" "$NGINX_CONF"
ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/${DOMAIN}"
rm -f /etc/nginx/sites-enabled/default

nginx -t && echo "       Config OK"
systemctl enable nginx
systemctl reload nginx

# ── 4. Instructies voor lokale machine ───────────────────────────────────────────
echo "[4/4] Hosts file instructies..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Voeg dit toe op de machine die de site bezoekt:"
echo ""
echo "   Linux/Mac:  sudo sh -c 'echo \"192.168.2.112 cyberstefan.nl www.cyberstefan.nl\" >> /etc/hosts'"
echo "   Windows:    Voeg toe aan C:\\Windows\\System32\\drivers\\etc\\hosts:"
echo "               192.168.2.112 cyberstefan.nl www.cyberstefan.nl"
echo ""
echo " Browser geeft een cert-waarschuwing (self-signed)."
echo " Klik 'Geavanceerd → Toch doorgaan' om de site te openen."
echo ""
echo " Wil je de waarschuwing vermijden? Installeer het cert als"
echo " vertrouwde CA op je machine:"
echo "   scp stefan@192.168.2.112:$SSL_DIR/cert.pem ~/cyberstefan-ca.pem"
echo "   # macOS:   open ~/cyberstefan-ca.pem  (dan Vertrouwen → Altijd)"
echo "   # Linux:   sudo cp ~/cyberstefan-ca.pem /usr/local/share/ca-certificates/cyberstefan.crt"
echo "   #          sudo update-ca-certificates"
echo "   # Windows: certlm.msc → Vertrouwde basiscertificaten → importeren"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Site live op: https://cyberstefan.nl"
