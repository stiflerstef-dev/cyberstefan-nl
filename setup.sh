#!/usr/bin/env bash
# Setup CTF workflow op de server — installeert dependencies en configureert systemd service
set -euo pipefail

WORKFLOW_DIR="$HOME/ctf-workflow"
VENV_DIR="$WORKFLOW_DIR/.venv"
SERVICE_NAME="ctf-writeups"
PORT="${CTF_PORT:-8000}"

echo "── CTF Workflow Setup ──────────────────────────────────"

if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 niet gevonden."
    exit 1
fi

echo "[1/5] Python venv aanmaken + packages installeren..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet -r "$WORKFLOW_DIR/api/requirements.txt"
echo "       Done (venv: $VENV_DIR)"

echo "[2/5] Mappen aanmaken..."
mkdir -p "$WORKFLOW_DIR/writeups" "$WORKFLOW_DIR/linkedin"

echo "[3/5] Script uitvoerbaar maken + symlink..."
chmod +x "$WORKFLOW_DIR/ctf-writeup.py"
mkdir -p "$HOME/.local/bin"
ln -sf "$WORKFLOW_DIR/ctf-writeup.py" "$HOME/.local/bin/ctf-writeup"
echo "       Symlink: ctf-writeup"

echo "[4/5] Env bestand controleren..."
ENV_FILE="/etc/ctf-workflow.env"
if [ ! -f "$ENV_FILE" ]; then
    # Maak een default env aan zonder ANTHROPIC_API_KEY (die vullen we later in)
    API_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    sudo tee "$ENV_FILE" > /dev/null <<EOF
ANTHROPIC_API_KEY=CHANGEME
CTF_API_KEY=${API_KEY}
CTF_PORT=8000
EOF
    sudo chmod 600 "$ENV_FILE"
    echo "       Aangemaakt: $ENV_FILE"
    echo "       CTF_API_KEY=${API_KEY}"
    echo "       Vergeet ANTHROPIC_API_KEY in te vullen!"
else
    echo "       Gevonden: $ENV_FILE"
fi

echo "[5/5] Systemd service installeren..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=CTF Writeups Web Server
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WORKFLOW_DIR/api
EnvironmentFile=/etc/ctf-workflow.env
ExecStart=$VENV_DIR/bin/uvicorn main:app --host 127.0.0.1 --port \${CTF_PORT:-8000}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
echo "       Service actief op poort $PORT"

echo ""
echo "Setup compleet!"
echo "Site (lokaal): http://192.168.2.112:${PORT}"
