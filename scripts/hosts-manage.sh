#!/bin/bash
# Beheert /etc/hosts entries voor CTF-machines (HTB/THM)
# Gebruik: hosts-manage.sh add <ip> <hostname>
#          hosts-manage.sh remove <hostname>
#          hosts-manage.sh list
MARKER="# ctf-managed"

case "$1" in
  add)
    IP="$2"
    HOST="$3"
    if ! [[ "$IP" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
      echo "Ongeldige IP: $IP" >&2; exit 1
    fi
    if ! [[ "$HOST" =~ ^[a-zA-Z0-9._-]+$ ]]; then
      echo "Ongeldige hostname: $HOST" >&2; exit 1
    fi
    # Verwijder eventuele bestaande entry voor deze hostname
    sed -i "/ ${HOST} ${MARKER}$/d" /etc/hosts
    echo "$IP $HOST $MARKER" >> /etc/hosts
    echo "OK"
    ;;
  remove)
    HOST="$2"
    if ! [[ "$HOST" =~ ^[a-zA-Z0-9._-]+$ ]]; then
      echo "Ongeldige hostname: $HOST" >&2; exit 1
    fi
    sed -i "/ ${HOST} ${MARKER}$/d" /etc/hosts
    echo "OK"
    ;;
  list)
    grep "$MARKER" /etc/hosts | awk '{print $1, $2}' || true
    ;;
  *)
    echo "Gebruik: $0 add <ip> <hostname> | remove <hostname> | list" >&2; exit 1
    ;;
esac
