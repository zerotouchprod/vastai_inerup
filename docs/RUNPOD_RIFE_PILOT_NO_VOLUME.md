# RunPod RIFE pilot — one isolated run, no Network Volume

Status: **prepared, not launched.** No Pod, Network Volume, or paid resource exists.
This document is the operator runbook and the GO/NO-GO record for the single pilot run.

## 1. Selected GPU (live catalog, Secure Cloud)

Read-only `GET /v2/catalog/gpus?include=AVAILABILITY&product=POD&cloud=SECURE`, **2026-10-16 05:04 UTC**:

| GPU | VRAM | $/hr | Availability | Listed CUDA hosts | DC |
|---|---|---|---|---|---|
| **RTX 3090 — selected** | 24 GB | **0.50** | LOW | 13.0, 13.3 | EU-CZ-1, EUR-IS-2 |
| RTX 4090 — fallback | 24 GB | 0.89 | MEDIUM | 12.8, 13.0, 13.2 | EU-RO-1 (MEDIUM) |
| RTX A4000 — **unavailable** | 16 GB | 0.25 | **NONE** | — | — |

Decision: **RTX 3090, EU-CZ-1, one Pod.** It is the cheapest suitable option, has 24 GB VRAM,
and Ampere SM 8.6 is inside the image's `TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.7;8.9;9.0;12.0"`.
RTX A4000 is not rentable at all. RTX 4090 stays the fallback if the 3090 offer disappears
(availability is LOW and volatile; re-check immediately before launch).

**Residual CUDA risk (unresolved by design):** the catalog lists no CUDA 12.6 host for the
RTX 3090 — the hosts advertise 13.0/13.3. A CUDA 12.6 container normally runs on a newer
driver, but `cuda_runtime_preflight.py` executes real kernels, so compatibility is proven
only by the authorized run itself. This cannot be settled without a paid GPU.

## 2. Immutable image (unchanged)

```
ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b
```

Source commit `15fd8abe95ed349c0ae2b34fb1fa2031bf491d6d`; image labels match the source revision
and the pinned manifest SHA `edcc8d3f80bb3fd8cc154903cf3e18af94309ce80ebe04eb9b9066dc8ecafa87`.
This pilot adds **no** other model, no image optimisation, and no production lifecycle change.

## 3. External one-shot controller (`scripts/runpod_pilot_controller.py`)

A standalone stdlib-only process with no link to the GPU Pod, the queue, or the application.
It owns the whole lifetime of one disposable Pod.

- **Durable identity.** The attempt (name, image, deadline) is written to an atomic `0600` state
  file *before* the create request; the provider Pod id is written the moment it is known.
- **Ambiguous create never retried.** RunPod's published create schema has no idempotency key, so
  a timeout/5xx is treated as ambiguous: the controller re-reads inventory and adopts the Pod by
  its unique name. A definite 4xx is a refusal with no Pod created.
- **Absolute deadline.** `deadline = provider createdAt + 1800s`, persisted. A restart re-reads the
  stored deadline; a skewed local clock can never extend it. The provider exposes no Pod TTL, so
  this controller — not the Pod — is the enforcement mechanism.
- **Fail-loud teardown.** Deletion is retried and every attempt is followed by an inventory
  re-check. Absence must be *proven*; otherwise the run reports `unresolved` and exits non-zero.
- **Single-Pod discipline.** The controller refuses to run if any Pod already exists, and refuses
  without `--resume` if its state file records a live Pod.

Worst-case overshoot past the deadline is bounded by the configured backoffs
(6 attempts x ~7.5 s of absence checks + 29 s of delete backoff) at **~74 s**.

## 4. Isolated test control plane (`scripts/runpod_pilot_test_control_plane.py`)

A throwaway stand-in for the worker API, so the pod never touches production: no application code,
no database, no queue, no object storage, no outbound calls.

- Implements only the six endpoints in `contracts/worker-api-v1.json`, plus a local input file and a
  local result sink.
- **Bearer token on everything.** The token is generated into an owner-only file
  (`--init-token`) and is never printed.
- **Exactly one job, ever.** After the single claim the plane answers 204 forever.
- **The job is not parameterisable from the network.** Input clip (generated locally with ffmpeg),
  cut range, mode, and destination are fixed at start-up; no request field selects a path or URL.
- **Loopback by default.** Binding elsewhere requires an explicit `--allow-non-loopback`.

Open operational decision at launch: the Pod must reach the plane. Either keep loopback and expose
it through a tunnel, or bind explicitly with `--allow-non-loopback` plus a firewall rule. The code
refuses the second option unless the operator acknowledges it.

## 5. Verification performed (no GPU used)

### Latest free operational readiness (2026-10-16)

- Controller and isolated plane are installed under systemd on `vps1748`.
- Plane is **active** on `127.0.0.1:8099` only. A dedicated SSH account/key provides a local forward to that loopback port; effective sshd policy denies shell, PTY, agent/X11, remote forwarding, and all forward targets except `127.0.0.1:8099`.
- The local SSH tunnel was exercised: unauthenticated claim through the tunnel returned 401; a forwarded port-22 target and reverse forwarding were both denied. The single test job was not claimed.
- Controller unit is enabled with `Restart=on-failure`, `RestartSec=15s`, persistent `StateDirectory`, `OnFailure` alert, and a restart wrapper that passes `--resume` after the durable create latch. `/etc/aividup-runpod-pilot/GO` is absent; systemd reports `ConditionResult=no`, controller inactive. No GO marker, state file, or create latch exists; **no create request can be issued**.
- Protected Pod env loader accepts only `AIVIDUP_*`, requires mode 0600, refuses the RunPod API key; Pod args accept only an `entrypoint`/`cmd` JSON object and reject group/world-writable files. A real controller `--dry-run` of the deployed config passed; worker token and private SSH key were redacted.
- Hermes job `aividup-runpod-pilot-teardown-alert` checks the systemd OnFailure marker every minute and sends one Telegram alert per attempt ID; it ran successfully with no false alert. The alert handler's dedupe logic was exercised (first alert emitted, duplicate silent).
- Local pilot tests after the protected env/args change: **125 passed**. Exact branch CI run [38859178898](https://github.com/zerotouchprod/vastai_inerup/actions/runs/38859178898) on `ad88469` passed **167 tests**; both image jobs were skipped. Anonymous GHCR HEAD still returns HTTP 200 for the requested immutable image digest.
- The one-time RunPod SSH path remains unverified from provider-side networks. No CPU or GPU Pod was created to test outbound TCP/22. The GPU run will fail before checkpoint download if this path is unavailable, while the external controller still owns the absolute 30-minute teardown deadline.
- Live provider snapshot at 2026-10-16 06:06 UTC: 0 Pods, 0 Network Volumes; RTX 3090 Secure/EU-CZ-1 `$0.50/h`, availability LOW. Recheck immediately before launch.

| Check | Result |
|---|---|
| Controller behaviour, 17 tests (fake clock/provider) | **PASS** — ambiguous create, delete failure, restart, inventory re-check, deadline absoluteness, single-Pod refusal |
| Controller over real HTTP, 12 tests (local REST v2 impersonator) | **PASS** — includes 500-create recovery with exactly one POST, 500-delete → unresolved, delete-that-landed-but-returned-500, refusal before POST |
| Isolated plane, 17 tests (incl. real `Worker` + `ControlPlaneClient` end-to-end on CPU with `passthrough`) | **PASS** — one job served, then permanently 204 |
| Mutation check (auth disabled, job guard disabled) | **5 tests fail** — the tests genuinely detect the breakage |
| Checkpoint bootstrap vs the live Release asset | **PASS** — 24,636,301 bytes, SHA-256 `45c7f741…f53f`, mode 0400, scratch 0700 |
| Bootstrap rejects a mismatching checkpoint hash | **PASS** — refused, no model materialised |
| Bootstrap rejects a mismatching manifest pin | **PASS** — refused before download |
| Live read-only client against the provider API | **PASS** — 0 Pods, 404 → `None`, no key leak |
| Full pilot suite, locally | **98 passed** |
| CI gate on tooling commit `dcc9069`, run [38854835769](https://github.com/zerotouchprod/vastai_inerup/actions/runs/38854835769) | **161 passed**; image jobs correctly skipped, published digests unchanged |
| Provider inventory after all preparation | 0 Pods, 0 Network Volumes |

Two real defects were found and fixed by these tests: a resumed controller reconciled a Pod but
never adopted it (would have orphaned an unmanaged Pod), and `int(deadline_seconds)` silently
collapsed a sub-second deadline to zero (would have deleted a Pod immediately).

## 6. Estimate

Per-second billing; container disk `$0.10/GB/month`; official docs state **no fees for data ingress
or egress**. No Network Volume, so no persistent-storage charge.

| Item | RTX 3090 (selected) | RTX 4090 (fallback) |
|---|---|---|
| GPU, 1800 s | $0.250000 | $0.445000 |
| Container disk, 20 GB, 1800 s | $0.001369 | $0.001369 |
| Transfer | $0.00 | $0.00 |
| **Expected total** | **$0.2514** | **$0.4464** |
| **Worst case (deadline + 74 s teardown)** | **$0.2617** | **$0.4647** |

The 24.6 MB checkpoint is fetched from a public GitHub Release asset, so that bandwidth is GitHub's,
not RunPod's. The `$1.25` figure is a *planning target only* — it is not a provider-enforced cap and
not an authorisation to spend. For contrast, leaving a 3090 running to the image's own 4-hour
`AIVIDUP_MAX_LIFETIME_SECONDS` would cost ~$2.00, which is exactly why the external deadline exists.

## 7. Launch sequence (only after separate explicit approval)

```bash
# 0. Re-check the catalog immediately; abort if RTX 3090 / EU-CZ-1 is gone.
# 1. Start the isolated plane (loopback + tunnel, or explicit non-loopback).
python3 scripts/runpod_pilot_test_control_plane.py --init-token /secure/path/plane.token
python3 scripts/runpod_pilot_test_control_plane.py --make-input /secure/path/input.mp4 --seconds 2
python3 scripts/runpod_pilot_test_control_plane.py \
  --token-file /secure/path/plane.token --input /secure/path/input.mp4 \
  --port 8099 --evidence /secure/path/plane-evidence.json

# 2. Run the controller under process supervision so a crash cannot orphan the Pod.
python3 scripts/runpod_pilot_controller.py \
  --state-file /var/lib/aividup-pilot/state.json \
  --pod-name aividup-rife-pilot-$(openssl rand -hex 4) \
  --image ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b \
  --gpu "NVIDIA GeForce RTX 3090" --data-centre EU-CZ-1 \
  --deadline-seconds 1800
# on restart after any crash: the same command plus --resume
```

Success requires: a completed attempt with worker timings, non-zero output bytes received by the
local sink, and `verified_absent: true` with exit code 0.

## 8. GO / NO-GO

**GO for the pilot run — conditional on all of the following, none of which this branch may self-authorise:**

1. Explicit spend approval for a bounded RTX 3090 run (~$0.26 worst case).
2. The controller running under supervision (systemd/tmux) with `--resume` documented, so a crash
   cannot orphan the Pod; provider has no TTL.
3. A decision on how the Pod reaches the isolated plane (loopback + tunnel, or explicit
   `--allow-non-loopback` + firewall).
4. The isolated plane's token file and evidence path living outside the repository.
5. A final catalog re-check confirming a Secure RTX 3090 offer in EU-CZ-1.

**NO-GO for anything else:** no production endpoint, no production job, no Network Volume, no second
model, no image optimisation, no production lifecycle change.

Accepted residual risks: CUDA 12.6 on a host advertising 13.x is unproven until the run itself;
availability is LOW and may vanish between the check and the launch; the controller is the only
deadline enforcement, so its host must actually stay alive.
