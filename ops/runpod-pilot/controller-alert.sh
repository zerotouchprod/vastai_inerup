#!/bin/sh
# Called by systemd OnFailure; the Hermes one-minute watchdog delivers this marker to Telegram.
set -eu
STATE_DIR=${AIVIDUP_PILOT_STATE_DIR:-/var/lib/aividup-runpod-pilot}
mkdir -p "$STATE_DIR"
chmod 0700 "$STATE_DIR"
INCIDENT="unknown-$(date -u +%Y%m%dT%H%M%SZ)"
if [ -s "$STATE_DIR/state.json" ]; then
    INCIDENT=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("attempt_id") or "unknown")' "$STATE_DIR/state.json" 2>/dev/null || printf 'unknown')
fi
TMP="$STATE_DIR/alert-pending.tmp.$$"
(umask 077; printf '%s\n' "$INCIDENT" > "$TMP")
chmod 0600 "$TMP"
mv -f "$TMP" "$STATE_DIR/alert-pending"
logger -p daemon.crit -t aividup-runpod-pilot \
    "controller failed for attempt $INCIDENT; teardown may be unresolved; inspect $STATE_DIR/state.json immediately"
