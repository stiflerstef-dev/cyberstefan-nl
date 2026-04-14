#!/usr/bin/env bash
# vpn-start.sh — Veilige OpenVPN launcher voor cyberstefan.nl/learning
#
# Gebruik (als root via sudo):
#   sudo /home/stefan/ctf-workflow/scripts/vpn-start.sh /path/to/config.ovpn
#
# Sudoers entry (zie docs/vpn-setup.md):
#   stefan ALL=(root) NOPASSWD: /home/stefan/ctf-workflow/scripts/vpn-start.sh
#
# Veiligheidsmaatregelen:
#   - Config moet binnen de geautoriseerde map liggen (geen path traversal)
#   - --script-security 0: alle script-hooks uitgeschakeld
#   - Alleen .ovpn extensie toegestaan

set -euo pipefail

AUTHORIZED_DIR="/home/stefan/ctf-workflow/editor/vpn_configs"
LOG_FILE="/home/stefan/ctf-workflow/editor/vpn.log"
PID_FILE="/tmp/cyberstefan_vpn.pid"
OPENVPN_BIN="/usr/sbin/openvpn"

if [[ $# -ne 1 ]]; then
    echo "Gebruik: $0 <config.ovpn>" >&2
    exit 1
fi

CONFIG="$1"

# Extensie check
if [[ "${CONFIG##*.}" != "ovpn" ]]; then
    echo "Fout: alleen .ovpn bestanden zijn toegestaan" >&2
    exit 1
fi

# Resolve naar absolute path en controleer dat het binnen AUTHORIZED_DIR ligt
if ! REAL_CONFIG=$(realpath -e "$CONFIG" 2>/dev/null); then
    echo "Fout: config bestand niet gevonden: $CONFIG" >&2
    exit 1
fi

REAL_DIR=$(realpath "$AUTHORIZED_DIR")

if [[ "$REAL_CONFIG" != "$REAL_DIR/"* ]]; then
    echo "Fout: config ligt buiten de toegestane map ($AUTHORIZED_DIR)" >&2
    exit 1
fi

# OpenVPN beschikbaar?
if [[ ! -x "$OPENVPN_BIN" ]]; then
    echo "Fout: $OPENVPN_BIN niet gevonden. Installeer via: sudo apt install openvpn" >&2
    exit 1
fi

# Stop eventueel lopende VPN
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill -TERM "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Start OpenVPN als daemon
exec "$OPENVPN_BIN" \
    --config "$REAL_CONFIG" \
    --script-security 0 \
    --verb 3 \
    --writepid "$PID_FILE" \
    --log "$LOG_FILE" \
    --daemon \
    --nobind
