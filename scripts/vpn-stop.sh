#!/usr/bin/env bash
# vpn-stop.sh — Stop de actieve OpenVPN verbinding
#
# Sudoers entry (zie docs/vpn-setup.md):
#   stefan ALL=(root) NOPASSWD: /home/stefan/ctf-workflow/scripts/vpn-stop.sh

set -euo pipefail

PID_FILE="/tmp/cyberstefan_vpn.pid"

if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        kill -TERM "$PID"
        echo "VPN gestopt (PID $PID)"
    else
        echo "Geen actief VPN proces gevonden"
    fi
    rm -f "$PID_FILE"
else
    # Fallback: kill alle openvpn processen
    pkill -TERM openvpn 2>/dev/null && echo "openvpn gestopt (pkill)" || echo "Geen openvpn proces gevonden"
fi
