#!/bin/sh
# Called by systemd; durable latch prevents an accidental second create on restart.
set -eu
STATE_DIR=/var/lib/aividup-runpod-pilot
STATE_FILE="$STATE_DIR/state.json"
ATTEMPT_LATCH="$STATE_DIR/create-attempted"

if [ -e "$ATTEMPT_LATCH" ]; then
    if [ ! -s "$STATE_FILE" ]; then
        logger -p daemon.crit -t aividup-runpod-pilot \
            'refusing restart: create-attempted latch exists but durable controller state is missing'
        exit 70
    fi
    set -- --resume
else
    umask 077
    : > "$ATTEMPT_LATCH"
    set --
fi

OBSERVER_STARTED_AT=$(/usr/bin/date +%s)
/usr/bin/python3 /opt/aividup-runpod-pilot/crash-loop-observer.py \
    --state-file "$STATE_FILE" \
    --plane-evidence "$STATE_DIR/plane-evidence.json" \
    --started-at-epoch "$OBSERVER_STARTED_AT" \
    --unit aividup-runpod-pilot.service &

exec /usr/bin/python3 /opt/aividup-runpod-pilot/runpod_pilot_controller.py \
    --state-file "$STATE_FILE" \
    --pod-name aividup-rife-pilot-one-shot \
    --image ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b \
    --gpu 'NVIDIA GeForce RTX 4090' \
    --data-centre EU-RO-1 \
    --deadline-seconds 1800 \
    --poll-seconds 15 \
    --pod-env-file /etc/aividup-runpod-pilot/pod.env \
    --pod-args-file /etc/aividup-runpod-pilot/pod-args.json \
    --api-key-file /home/informaten/runpod.env \
    "$@"
