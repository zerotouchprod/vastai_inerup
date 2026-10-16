#!/usr/bin/env python3
"""Deliver one Telegram alert when the systemd controller reports a failure."""
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("AIVIDUP_PILOT_STATE_DIR", "/var/lib/aividup-runpod-pilot"))
pending = ROOT / 'alert-pending'
sent = ROOT / 'alert-sent'
state_path = ROOT / 'state.json'
if not pending.is_file():
    raise SystemExit(0)
incident = pending.read_text().strip()
if not incident or (sent.exists() and sent.read_text().strip() == incident):
    raise SystemExit(0)
try:
    state = json.loads(state_path.read_text())
except Exception:
    state = {}
pod_id = state.get('pod_id') or 'unknown (check inventory by name)'
phase = state.get('phase') or 'missing-state'
verified = state.get('verified_absent')
if verified is True or phase == 'done':
    message = (
        f'RunPod pilot controller failure alert for attempt {incident}: '
        f'pod {pod_id}, phase={phase}, inventory now proves absent. Check systemd journal.'
    )
else:
    message = (
        f'CRITICAL: RunPod pilot controller failed for attempt {incident}; '
        f'pod {pod_id}, phase={phase}, verified_absent={verified}. '
        'It may still be billing. Check `systemctl status aividup-runpod-pilot` and '
        'RunPod inventory immediately.'
    )
# Persist before delivery so a transport retry cannot spam. The local journal marker remains.
tmp = sent.with_suffix('.tmp')
tmp.write_text(incident + '\n')
os.chmod(tmp, 0o600)
os.replace(tmp, sent)
print(message)
