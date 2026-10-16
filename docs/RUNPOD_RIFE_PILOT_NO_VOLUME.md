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
- **Ambiguous create never retried.** RunPod's create schema has no idempotency key. On timeout/408/429/5xx, a successful body without a Pod ID, or a crash after the pre-POST intent, the durable state is `create_outcome_unknown`; the controller never re-POSTs. It polls inventory by the unique Pod name for an initial ~67 seconds. If still not visible, it remains alive in `unresolved` and rechecks every 60 seconds indefinitely (including across `--resume`); a late Pod is adopted using provider `createdAt` and immediately torn down if its absolute deadline has elapsed. If inventory remains unavailable indefinitely, the watchdog alerts and manual provider-console action may still be needed.
- **Absolute deadline.** `deadline = provider createdAt + 1800s`, persisted. A restart re-reads the stored deadline; a skewed local clock can never extend it. The provider exposes no Pod TTL, so this controller — not the Pod — is the enforcement mechanism.
- **Fail-loud teardown.** Deletion is retried and every attempt is followed by an inventory re-check. Absence must be *proven*; otherwise the run reports `unresolved` and exits non-zero instead of claiming success.
- **Single-Pod discipline.** The controller refuses to run if any Pod already exists, and refuses without `--resume` if its state file records a live or ambiguous create.

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
- Controller unit is enabled with `Restart=on-failure`, `RestartSec=15s`, `StartLimitIntervalSec=300s`, `StartLimitBurst=5`, persistent `StateDirectory`, and a restart wrapper that passes `--resume` after the durable create latch. `/etc/aividup-runpod-pilot/GO` is absent; systemd reports `ConditionResult=no`, controller inactive. No GO marker, state file, or create latch exists; **no create request can be issued**.
- Ambiguous create never re-POSTs. After the initial bounded search the controller keeps the same process alive with durable `unresolved` state and polls once/minute until it finds the late Pod; crash recovery repeats this via `--resume`. Repeated process crashes are bounded to five per five-minute window.
- A no-network systemd fake-provider integration test exercised crash→restart→`--resume`: `NRestarts=1`, fake create count 1, fake Pod removed/verified absent, and the independent watchdog emitted a critical alert while the fake Pod was still live. A prior unit with `OnFailure` attached did not emit its marker on an automatic restart; the independent watchdog is primary for restart detection, with `OnFailure` retained for terminal failure.
- Protected Pod env loader accepts only `AIVIDUP_*`, requires mode 0600, refuses the RunPod API key; Pod args accept only an `entrypoint`/`cmd` JSON object and reject group/world-writable files. The actual dry-run of the deployed config passed; secrets were redacted. The Pod startup script now requires an HTTP 401 probe through the tunnel before checkpoint bootstrap.
- Hermes alert job checks `NRestarts`, service state, controller heartbeat age, ambiguous state, and the durable `OnFailure` marker every minute; empty/no-alert path is silent.
- Local pilot suite: **139 passed in 46.15s**. Exact GitHub Actions run [38871609434](https://github.com/zerotouchprod/vastai_inerup/actions/runs/38871609434), SHA `88277706ecf5947ef5098dd64fabe76f8dfbb64a`: `tests` passed including CPU-only image acceptance; `image` and `runpod-pilot-image` were skipped (`publish_runpod_pilot=false`). No image was published; the immutable pilot digest is unchanged.
- The one-time RunPod SSH path remains unverified from provider-side networks. No CPU or GPU Pod was created to test outbound TCP/22. The GPU run will fail before checkpoint download if this path is unavailable, while the external controller owns the absolute 30-minute teardown deadline.
- Live provider snapshot at 2026-10-16 06:06 UTC: 0 Pods, 0 Network Volumes; RTX 3090 Secure/EU-CZ-1 `$0.50/h`, availability LOW. Recheck immediately before launch.

| Check | Result |
|---|---|
| Controller behavior, 20 tests (fake clock/provider) | **PASS** — ambiguous create, late visibility during `--resume`, bounded DELETE, absolute deadline, heartbeat and single-Pod refusal |
| Controller over real HTTP, 14 tests (local REST v2 impersonator) | **PASS** — 500/408/malformed create recovery without duplicate POST, delete failures, inventory verification |
| Protected Pod configuration, 7 tests | **PASS** — owner-only env file, API key exclusion, command-file permission checks, dry-run redaction and HTTP readiness probe |
| Independent watchdog, 8 tests | **PASS** — GO gating, active/failure states, restart count, stale heartbeat and deduplication |
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

## 9. Live run #1 — 2026-10-16 (executed; worker never reached RIFE)

Spend was approved for one Pod. The approved RTX 3090 / EU-CZ-1 Secure offer disappeared before
launch (`availability=NONE`, zero datacentres at 10:02 UTC after LOW at 08:46), so the run used the
documented fallback under a separate explicit decision: **RTX 4090 Secure, EU-RO-1, $0.89/h**, one
Pod, absolute 1800 s deadline, no Network Volume, no retries.

| Fact | Measured |
|---|---|
| create requested → provider `createdAt` | 10:04:41.457 → 10:04:41.954 UTC (0.5 s) |
| Pod id / datacentre | `kx35gksg1mtjfz` / EU-RO-1 |
| **cold start** (`createdAt` → first working SSH tunnel from the Pod) | **≈154 s** (first accepted key 10:07:16 UTC) |
| **outbound TCP/22 Pod → vps1748** | **PASS** — `sshd` accepted the restricted key from the Pod egress IP; 62 sessions during the run |
| restricted tunnel + HTTP 401 probe before bootstrap | **PASS** — execution advanced past the probe step |
| isolated plane jobs claimed | **0** (the single job is still unused) |
| failure | `python3: can't open file '/opt/aividup-runpod-pilot/runpod_checkpoint_bootstrap.py'` (§10) |
| container restarts | 62 tunnel handshakes in ~16 min — the entrypoint crash-looped |
| teardown | Pod reached `EXITED`; controller logged `is EXITED; tearing down now`, 1 DELETE attempt, `verified_absent: true`, exit code 0 |
| provider inventory after | 0 Pods, 0 Network Volumes |
| wall clock | 10:04:42 → 10:23:47 UTC = **1145 s** |
| **cost** | 4090 $0.89/h × 1145 s ≈ **$0.283** + 20 GB disk ≈ $0.001 → **≈$0.284** |

CUDA/RIFE on a real GPU is still **unverified**: the run failed before checkpoint download, so
`cuda_runtime_preflight` and RIFE inference never executed. The absolute-deadline teardown path was
not exercised (the Pod exited early); the early-exit teardown path was, against the real provider.
The worst-case $1.25 planning figure was never approached.

## 10. Defect found by run #1 and fixed

`ops/runpod-pilot/pod-args.json` invoked the bootstrap at a **host** path
(`/opt/aividup-runpod-pilot/runpod_checkpoint_bootstrap.py`) that does not exist inside the
immutable image; `docker/Dockerfile.runpod-pilot` copies it to
`/opt/aividup/runpod_checkpoint_bootstrap.py`. Every container restart re-ran the tunnel and the 401
probe successfully and then died on the missing file.

Fix: the Pod args now run `python3 /opt/aividup/runpod_checkpoint_bootstrap.py &` (the same path and
interpreter the image's own `ENTRYPOINT` uses). Adding `AIVIDUP_IDLE_EXIT_SECONDS` or any other
behaviour change is explicitly out of scope.

Regression test `tests/unit/test_runpod_pilot_controller_config.py::test_pod_args_bootstrap_path_exists_inside_the_immutable_image`
derives the expected path from the Dockerfile `COPY` destination and asserts the Pod args use it and
never reference a host-only `/opt/aividup-runpod-pilot/` path. No GPU-side test could have caught
this class of defect; the container filesystem was the only place it could show up.

## 11. Live run #2 — 2026-10-16 (startup passed; video input failed)

The second separately approved Pod used RTX 4090 Secure / EU-RO-1 at `$0.89/h`, the same immutable
image and checkpoint, 1800-second absolute deadline, no volume, one Pod and no retries.

| Fact | Result |
|---|---|
| Pod / attempt | `sztqbrmskj4z0k` / `5f19bbaebd529def` |
| provider `createdAt` / controller stop | 11:03:23.618 / 11:06:01 UTC |
| cold start (`createdAt` → accepted SSH tunnel) | **150.382 s** |
| bootstrap stages / job claim | `started`, `ready`; exactly one job claimed |
| worker failure | `input_invalid`; ffmpeg failed reading/cutting the input; no output/completion |
| immediate teardown | independent observer saw plane failure, stopped controller; one DELETE; `verified_absent: true`, controller exit 0, provider inventory 0 Pods |
| wall time / cost estimate | 157.382 s / **≈$0.03903** (GPU + estimated disk; not an invoice) |

**CUDA/RIFE preflight: PROBABLE_PASS (control-flow evidence).** With pipeline mode and GPU checks
not disabled, `worker_start.sh` executes `cuda_runtime_preflight.py` before polling for a job. The
configured RIFE probe invokes `RIFENative.process_frames` on a two-frame synthetic clip. Reaching
and claiming the job is strong evidence that both gates passed, but the Pod's raw stdout was not
retrievable after teardown (provider GET/log endpoints returned 404). **RIFE_VIDEO_E2E: NOT_TESTED**:
the real two-second task failed before RIFE processed its frames.

### Root cause: task URLs advertised the server's private listener

`IsolatedControlPlane.base_url` is the VPS listener `http://127.0.0.1:8099/api/worker`. The Pod,
however, reaches that service through its own SSH-forward listener at
`http://127.0.0.1:18099/api/worker`. `build_task()` used the VPS base URL for **both** `input_url`
and `output.url`; input therefore pointed at a Pod-local port with no listener, and output would
have been equally unreachable. This matches the `input_invalid` failure, although the exact ffmpeg
stderr is unavailable and the specific failed request cannot be proven from Pod logs.

Fixed in commit `7b6f602`: new `advertised_base_url` is separate from bind/listen address; service
still binds `127.0.0.1:8099` but task URLs advertise `127.0.0.1:18099` for both input and output.
Regression test explicitly uses different listener/advertised ports and checks both returned URLs.

## 12. CPU-only end-to-end over the real restricted SSH forward

A fresh one-shot plane/task was used; the run #2 evidence was archived first, not reset. The actual
restricted SSH local-forward and production `Worker` class were exercised on the controller host.
No RunPod API call, Pod, GPU, or production job was involved.

| Stage | Result |
|---|---|
| server bind / advertised task URL | `127.0.0.1:8099` / `127.0.0.1:18099` |
| SSH forward / unauthorized probe | **PASS** / HTTP 401 |
| claim → ffmpeg input cut → CPU passthrough → PUT → complete | **PASS**, exactly one claimed and completed; zero failures |
| output | **35,249 bytes**, SHA-256 `8c747834ac5b4f420ff7afa25f4b188cec1b86ba0d95ba93bcbb70b46312bf0a`; independently re-read from the captured output file and matches sink evidence |
| timings | boot-to-claim 0.08s; cut 0.31s; passthrough 0.00s; verify 0.13s; upload 0.01s; work 0.51s; full E2E 0.588s |

Durable evidence is under `/var/lib/aividup-runpod-pilot/cpu-e2e-2026-10-16/` (`summary.json`,
`evidence.json`, output MP4); raw run #2 plane evidence is preserved under `archive/run-2/`.
Total estimated paid spend across runs #1 and #2 is **≈$0.323**, not a final provider invoice.
The controller GO gate remains closed; a third paid GPU rental is **not authorized**.

## 13. Preflight stdout/stderr persistence for a future GPU attempt

Commit `43e98d1` adds a Python wrapper in the Pod args that intercepts exactly the image's
`/opt/aividup/cuda_runtime_preflight.py` invocation. It captures stdout and stderr separately,
combines them for transport, and PUTs the log through the already-open authenticated SSH tunnel to
the isolated plane sink **before the worker can claim a job**. The sink redacts the worker bearer
token, atomically writes a mode-0600 `diagnostics-*.log` under
`/var/lib/aividup-runpod-pilot/worker-output/`, and records path, bytes and SHA-256 in the plane
evidence. If this PUT fails, the wrapper exits 74 and the worker does not proceed to claim.

CPU-only real-forward E2E verified the diagnostics sink and persistence/redaction: an 83-byte
synthetic CUDA/RIFE preflight log was saved with SHA-256
`40ea931eac06e95070ff7bb1c6f71b3ca81995d01b967c2c29b29dcb571b39db`, matching evidence; the bearer
token is absent from the file. The same run completed the 2-second ffmpeg → CPU passthrough → PUT →
complete chain. This proves the tunnel/sink/persistence path, **not** that a future GPU Pod will emit
or pass CUDA/RIFE logs.

At 2026-10-16 12:08 UTC the fresh unused plane job is
`pilot-3bfa9c78-e205-4eb7-b9f8-b19aa835dbb9`; evidence path is
`/var/lib/aividup-runpod-pilot/plane-evidence.json` and is not yet created because the job has not
been claimed. Secure RTX 4090 EU-RO-1 was LOW at `$0.89/h`; provider inventory had 0 Pods. Controller
GO remains absent and inactive.

## 14. Live run #3 — 2026-10-16 (restarted before worker claim; stopped, no retry)

One RTX 4090 Secure / EU-RO-1 Pod `j98pz0w7kbe693` was created at 12:25:14.143 UTC with the pinned
image, no Network Volume, and absolute deadline 12:55:14.143 UTC. The controller was manually stopped
at 12:30:59 after repeated tunnel handshakes with no plane/worker evidence; it issued one DELETE and
verified absence by 12:31:01. Final provider inventory was 0 Pods. Estimated billed lifetime was
346.857 s, **≈$0.08602** (GPU + estimated disk; not an invoice).

Evidence: `/var/lib/aividup-runpod-pilot/run3-evidence.json` (mode 0600), controller `state.json`,
`archive/run-2/` preserved the prior attempt, and host sshd journal lines show **10 accepted SSH
sessions** from the Pod egress IP between 12:28:26 and 12:31:01, roughly every 17–18 seconds. A live
Pod runtime sample at 12:30:14 showed uptime 0, CPU 9%, GPU util 0%, GPU memory util 0%. The plane
never wrote evidence: no bootstrap stages, no diagnostic upload, no job claim, and no output. The
CUDA/RIFE preflight and real video render were therefore **NOT REACHED / NOT TESTED**. A live GET to
the provider Pod-logs endpoint timed out; no container stdout/stderr was obtained.

### Observer failure found

The short-lived restart-loop observer passed `journalctl --since` an ISO string with `T` and `+00:00`
(`2026-10-16T12:24:56+00:00`). `journalctl` rejected it (`Failed to parse timestamp`); the observer
silently saw zero sessions and did not trigger its threshold. The Pod was stopped manually after the
repeated 17-second SSH pattern was observed. Do not treat that observer as a verified safeguard
until its timestamp format and query errors are fixed/tested. Controller deletion and inventory
verification did work.

This was the last approved rental; **no fourth run or automatic retry is authorized**. GO has been
removed again, controller is inactive, and all run #3 evidence is retained. Any additional paid run
requires a separate explicit approval.
