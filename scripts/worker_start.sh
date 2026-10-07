#!/usr/bin/env bash
# Entrypoint of the AIVIDUP GPU pull worker image (docker/Dockerfile.worker).
#
# Required env:   AIVIDUP_API_URL        e.g. https://aividup.com/api/worker
#                 AIVIDUP_WORKER_TOKEN   shared secret (never printed, never put on a command line)
# Provider instance id: AIVIDUP_GPU_INSTANCE_ID, CONTAINER_ID or VAST_CONTAINERLABEL.
# Worker id: unique UUID for this process; a new boot requires a new lease generation.
# Optional env: AIVIDUP_PROCESSOR (pipeline|ffmpeg|passthrough, default pipeline)
#                 AIVIDUP_IDLE_EXIT_SECONDS (default 300)   leave after this long without work (stop paying for an idle GPU)
#                 AIVIDUP_MAX_LIFETIME_SECONDS (default 14400)  hard cap on how long the container lives
#                 AIVIDUP_MAX_RESTARTS (must be 0)    in-lease restarts are fenced; recover with a new lease
#                 AIVIDUP_POLL_SECONDS (default 3)   AIVIDUP_RESTART_BACKOFF (unused; compatibility only)
#                 AIVIDUP_SELF_DESTROY=1                    after exit, destroy this Vast instance (needs CONTAINER_ID + CONTAINER_API_KEY)
#                 AIVIDUP_SKIP_GPU_CHECK=1 | AIVIDUP_DRY_RUN=1 | PYTHON=<interpreter>
#
# Exit codes: 0 idle/lifetime exit, 2 bad configuration, 3 GPU unusable, 4 gave up after repeated crashes, 143 stopped by signal.
set -uo pipefail
set -m   # every background job gets its own process group, so a crashed worker's leftovers can be killed as a unit

log() { printf '%s [worker_start] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { local code="$1"; shift; log "ERROR: $*"; maybe_self_destroy "$*"; exit "$code"; }

PYTHON="${PYTHON:-python3}"
API_URL="${AIVIDUP_API_URL:-}"
PROCESSOR="${AIVIDUP_PROCESSOR:-pipeline}"
IDLE_EXIT="${AIVIDUP_IDLE_EXIT_SECONDS:-300}"
MAX_LIFETIME="${AIVIDUP_MAX_LIFETIME_SECONDS:-14400}"
MAX_RESTARTS="${AIVIDUP_MAX_RESTARTS:-0}"
POLL="${AIVIDUP_POLL_SECONDS:-3}"
BACKOFF="${AIVIDUP_RESTART_BACKOFF:-5}"

resolve_provider_instance_id() {
  if [[ -n "${AIVIDUP_GPU_INSTANCE_ID:-}" ]]; then printf '%s' "$AIVIDUP_GPU_INSTANCE_ID"; return; fi
  if [[ -n "${CONTAINER_ID:-}" ]]; then printf '%s' "$CONTAINER_ID"; return; fi
  if [[ -n "${VAST_CONTAINERLABEL:-}" ]]; then printf '%s' "${VAST_CONTAINERLABEL#C.}"; return; fi
}

# Best effort: the control plane's lease reaper is the authoritative cleanup; this just stops billing sooner.
maybe_self_destroy() {
  [[ "${AIVIDUP_SELF_DESTROY:-0}" == "1" ]] || return 0
  if [[ -z "${CONTAINER_ID:-}" || -z "${CONTAINER_API_KEY:-}" ]]; then
    log "self-destroy requested but CONTAINER_ID/CONTAINER_API_KEY missing - skipping"; return 0
  fi
  if [[ "${AIVIDUP_DRY_RUN:-0}" == "1" ]]; then log "DRY RUN: would destroy instance ${CONTAINER_ID}"; return 0; fi
  log "destroying instance ${CONTAINER_ID} ($1)"
  local i
  for i in 1 2 3; do
    curl -fsS -m 20 -X DELETE -H "Authorization: Bearer ${CONTAINER_API_KEY}" \
      "https://console.vast.ai/api/v0/instances/${CONTAINER_ID}/" >/dev/null 2>&1 && { log "destroy requested"; return 0; }
    sleep $((i * 3))
  done
  log "WARNING: could not destroy instance ${CONTAINER_ID}; the control plane will reap it when the lease expires"
}

PROVIDER_INSTANCE_ID="$(resolve_provider_instance_id)"
WORKER_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
[[ -n "$API_URL" ]] || die 2 "AIVIDUP_API_URL is not set"
[[ -n "${AIVIDUP_WORKER_TOKEN:-}" ]] || die 2 "AIVIDUP_WORKER_TOKEN is not set"
[[ -n "$PROVIDER_INSTANCE_ID" ]] || die 2 "provider instance id is unavailable"
[[ -n "${AIVIDUP_GPU_LEASE_ID:-}" && -n "${AIVIDUP_BOOT_ID:-}" ]] || die 2 "lease/boot identity is unavailable"
case "$PROCESSOR" in pipeline|ffmpeg|passthrough) ;; *) die 2 "unknown AIVIDUP_PROCESSOR '$PROCESSOR'";; esac
for v in IDLE_EXIT MAX_LIFETIME MAX_RESTARTS POLL BACKOFF; do [[ "${!v}" =~ ^[0-9]+$ ]] || die 2 "$v must be a non-negative integer (got '${!v}')"; done
[[ "$MAX_RESTARTS" == 0 ]] || die 2 "in-lease restarts are disabled; issue a new lease/boot generation instead"
[[ "$API_URL" =~ ^https?:// ]] || die 2 "AIVIDUP_API_URL must start with http:// or https://"
[[ "$API_URL" == http://* && "$API_URL" != http://127.0.0.1* && "$API_URL" != http://localhost* ]] \
  && log "WARNING: control plane URL is plain http - the worker token travels unencrypted"

log "worker id=${WORKER_ID} processor=${PROCESSOR} api=${API_URL} idle_exit=${IDLE_EXIT}s max_lifetime=${MAX_LIFETIME}s image_rev=$(cat /etc/aividup_revision 2>/dev/null || echo n/a)"

if [[ "$PROCESSOR" == "pipeline" && "${AIVIDUP_SKIP_GPU_CHECK:-0}" != "1" && "${AIVIDUP_DRY_RUN:-0}" != "1" ]]; then
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L || log "nvidia-smi not available"
  "$PYTHON" - <<'PY' || die 3 "GPU is not usable from PyTorch (bad host / driver mismatch) - refusing to take work"
import sys, torch
if not torch.cuda.is_available():
    sys.exit("torch.cuda.is_available() is False")
x = torch.randn(256, 256, device="cuda"); torch.cuda.synchronize()   # really touch the device
print(f"GPU ok: {torch.cuda.get_device_name(0)} cc={torch.cuda.get_device_capability(0)} torch={torch.__version__} cuda={torch.version.cuda}")
PY
fi

CMD=("$PYTHON" -m src.worker --api "$API_URL" --worker-id "$WORKER_ID" --provider-instance-id "$PROVIDER_INSTANCE_ID" --gpu-lease-id "$AIVIDUP_GPU_LEASE_ID" --boot-id "$AIVIDUP_BOOT_ID" --processor "$PROCESSOR"
     --poll-seconds "$POLL" --idle-exit-seconds "$IDLE_EXIT")
if [[ "${AIVIDUP_DRY_RUN:-0}" == "1" ]]; then
  log "DRY RUN: ${CMD[*]}"; maybe_self_destroy "dry run"; exit 0
fi

STOP=0; CHILD=0
on_signal() { STOP=1; log "signal received - stopping worker"; [[ "$CHILD" -gt 0 ]] && kill -TERM -- "-$CHILD" 2>/dev/null; }
trap on_signal TERM INT

START=$(date +%s); FAILS=0; REASON=""
while true; do
  REMAINING=$(( MAX_LIFETIME - ($(date +%s) - START) ))
  if (( REMAINING <= 0 )); then REASON="max lifetime reached"; RC=0; break; fi

  timeout --signal=TERM --kill-after=20 "${REMAINING}s" "${CMD[@]}" &
  CHILD=$!
  wait "$CHILD"; RC=$?
  kill -KILL -- "-$CHILD" 2>/dev/null   # never leave an orphaned worker next to its replacement (two workers on one attempt)
  CHILD=0
  (( STOP == 1 )) && { log "stopped by signal"; exit 143; }   # an orchestrator is in charge: no self-destroy

  case "$RC" in
    0)   REASON="idle for ${IDLE_EXIT}s"; break ;;
    124) REASON="max lifetime reached"; RC=0; break ;;
    *)   FAILS=$((FAILS + 1))
         log "worker exited with code ${RC} (crash ${FAILS}/${MAX_RESTARTS})"
         if (( FAILS >= MAX_RESTARTS )); then REASON="too many crashes"; RC=4; break; fi
         sleep $(( FAILS * BACKOFF )) ;;   # unreachable: nonzero MAX_RESTARTS is rejected; recovery requires a new lease/boot generation
  esac
done

log "exiting: ${REASON}"
maybe_self_destroy "$REASON"
exit "$RC"
