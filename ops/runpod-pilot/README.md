# Free operational setup — not armed for a paid launch

These unit files use existing host components only. The controller is **gated** by
`/etc/aividup-runpod-pilot/GO`, which must not be created until the later paid-run consent.
It will not POST a create request at boot/restart without that file.

## Supervision and durable recovery

- Controller state + `create-attempted` latch: `/var/lib/aividup-runpod-pilot/` (`StateDirectoryMode=0700`, outside `/tmp`).
- `Restart=on-failure`, `RestartSec=15s`, `StartLimitIntervalSec=300s`, `StartLimitBurst=5`.
- Wrapper chooses initial create only when there is no latch. Once the first attempt begins,
  restarts always pass `--resume`; if the latch exists but state is missing, it **refuses** instead
  of issuing a second POST.
- An ambiguous POST is never replayed. After a bounded 67-second inventory search, the controller
  remains in-process in `unresolved` and rechecks every 60 seconds indefinitely; if a late Pod
  appears it adopts the provider `createdAt` deadline and deletes it. A hard crash restarts via
  `--resume`; five repeated process failures in five minutes trip the start limit and the watchdog
  alerts, instead of causing an infinite rapid restart loop.
- Unit requires the isolated plane, uses the immutable image digest, `1800s` deadline, RTX 3090
  EU-CZ-1, no Network Volume, and restarts cannot extend provider `createdAt + 1800s`.
- `OnFailure` writes a durable marker on terminal failures. The independent Hermes watchdog also
  checks systemd `ActiveState`/`NRestarts`, ambiguous state, and controller heartbeat age every minute.
  A real local systemd test observed that `OnFailure` did not run on an automatic restart; the
  independent watchdog detected `NRestarts=1` and alerted while the fake Pod was still live.

## Private network path

- Test plane binds only `127.0.0.1:8099`; no public HTTP listener or production API route.
- The Pod opens an outbound SSH local-forward to `195.234.126.233:22`; its local
  `127.0.0.1:18099` forwards only to the host's `127.0.0.1:8099`.
- SSH login is a dedicated no-shell user and an Ed25519 key restricted by `authorized_keys` and
  `sshd Match` to *local* forwarding to exactly `127.0.0.1:8099`; no PTY/agent/X11/remote forward.
  Host key is pinned in the Pod args. The bearer test token is additionally required by the plane.
- The immutable image lacks `ssh`; the Pod's create args install only `openssh-client` into the
  ephemeral container before bootstrap. This changes neither the image nor production code.
- Pod env/args are loaded from protected config files; controller dry-run redacts all secret keys.
  The RunPod API key is explicitly forbidden from Pod env.
- The plane binds on the VPS-side `127.0.0.1:8099`; task input/output URLs advertise the Pod-side forward at `http://127.0.0.1:18099/api/worker`.
- Before worker claim, the Pod's Python wrapper captures separate CUDA/RIFE preflight stdout and stderr, uploads their combined text via the authenticated tunnel sink, and fails closed if persistence fails. The plane redacts the worker bearer token, atomically saves `diagnostics-*.log` mode 0600 under `worker-output/`, and records file path, byte count, and SHA-256 in evidence.

## CPU-only end-to-end through the restricted SSH forward

Run `ops/runpod-pilot/cpu-ssh-forward-e2e.py` on the isolated controller host only after archiving
any prior plane evidence and ensuring port 8099 is free. It starts a fresh one-job plane, opens the
real restricted SSH local-forward (`18099 -> host loopback:8099`), sends a synthetic preflight log
through the authenticated sink, then runs the real `Worker` with `ffmpeg` plus the CPU-only
`passthrough` processor. It verifies claim → input fetch/cut → PUT output → complete, non-zero output
bytes, redacted durable diagnostics, and captured output SHA-256 against sink evidence. It
makes no RunPod API call and uses no GPU. Use a new evidence path and output directory per invocation;
never reset `claims_served` on an already-used plane instance.

The unit regression test deliberately separates the server listener port from the advertised
client URL and checks both returned URLs (`input_url` and `output.url`).


## Current host state (vps1748, after paid runs #1–#2 and the CPU-only tunnel E2E)

- `/opt/aividup-runpod-pilot/` contains the root-owned read-only controller and isolated-plane scripts.
- `aividup-pilot-plane.service` is enabled and running on `127.0.0.1:8099`; it advertises task URLs at `http://127.0.0.1:18099/api/worker` and persists sink payloads under `/var/lib/aividup-runpod-pilot/worker-output/`. Current fresh job id: `pilot-3bfa9c78-e205-4eb7-b9f8-b19aa835dbb9` (zero claims, no evidence file yet).
- SSH has the dedicated `aividup-pilot-tunnel` account; effective sshd policy is `AllowTcpForwarding local`, `PermitOpen 127.0.0.1:8099`, `ForceCommand /usr/sbin/nologin`, no PTY/agent/X11. The private key remains protected. No extra public HTTP port was opened.
- The host-side SSH tunnel was exercised through localhost: it reaches the plane, unauthenticated claims return 401, forwarding to port 22 is denied, remote forwarding is denied.
- `aividup-runpod-pilot.service` is enabled but inactive; `/etc/aividup-runpod-pilot/GO` is absent. The controller state/latch for run #2 are retained (`phase=done`, `verified_absent=true`); run #1 state/latch/evidence are preserved under `archive/run-1/`. No new create request can occur without a fresh explicit GO.
- Hermes job `aividup-runpod-pilot-teardown-alert` checks `ActiveState`, `NRestarts`, ambiguous state, heartbeat age, and the durable `OnFailure` marker every minute. The independent observer also stopped run #2 immediately after the isolated plane recorded `input_invalid`.
- Provider inventory after run #2: **0 Pods**. No Network Volume was requested or created; the volumes REST path returns 404 on this account/API endpoint.
- **Run #1** (2026-10-16 10:04:42–10:23:47 UTC): documented fallback RTX 4090 Secure/EU-RO-1, `$0.89/h`; Pod `kx35gksg1mtjfz`, approx **$0.284**, `verified_absent=true`. Outbound TCP/22 worked; failure was the host-only bootstrap path, since fixed (see `docs/RUNPOD_RIFE_PILOT_NO_VOLUME.md` §9–§10).
- **Run #2** (2026-10-16 11:03:23–11:06:01 UTC): one RTX 4090 Secure/EU-RO-1 Pod `sztqbrmskj4z0k`; approx **$0.039**. Tunnel and worker startup succeeded; worker claimed the one job, then input read/cut failed with `input_invalid`. Control-flow indicates **CUDA/RIFE preflight probable pass** (the worker polls only after it passes); real two-second-video RIFE/output is **not tested**. Observer stopped the controller immediately; `verified_absent=true`, inventory 0. Evidence is in `/var/lib/aividup-runpod-pilot/run2-evidence.json`, plus archived raw plane evidence at `archive/run-2/plane-evidence.json`.
- Source diagnosis: both `input_url` and `output.url` were generated from the VPS listener `127.0.0.1:8099`; the Pod-side tunnel endpoint is `127.0.0.1:18099`. Fixed in commit `7b6f602` by adding `advertised_base_url`, keeping bind/listen on 8099 and advertising 18099 for both task URLs.
- **CPU-only SSH-forward E2E after log capture** (2026-10-16 12:08 UTC): diagnostics PUT + claim → ffmpeg cut → CPU passthrough → video PUT → complete all passed; 1 claim/completion, 0 failures. Synthetic preflight log was redacted and persisted as 83 bytes, SHA-256 `40ea931eac06e95070ff7bb1c6f71b3ca81995d01b967c2c29b29dcb571b39db`; 2-second video output **35,249 bytes**, SHA-256 `8c747834ac5b4f420ff7afa25f4b188cec1b86ba0d95ba93bcbb70b46312bf0a`. Both match evidence. Durable result: `/var/lib/aividup-runpod-pilot/cpu-e2e-log-capture-2026-10-16/summary.json` and `evidence.json`.
- Run #3 preflight at 12:08 UTC: RTX 4090 Secure/EU-RO-1 LOW `$0.89/h`; 0 Pods; controller inactive, GO absent; watchdog cron last status `ok`. Estimate ~$0.465 max under normal teardown, **not** a provider hard cap. No launch has been authorized or started.

The Pod-side outbound TCP/22 path is now proven by both paid runs; the restricted tunnel and 401 pre-bootstrap probe also pass in the CPU-only forward E2E. The application-level tunnel URL mismatch found in run #2 is fixed and the full CPU worker flow passed. Still unverified: RIFE processing of the real two-second clip on GPU, and provider-side output path under an actual GPU worker. No third paid launch is authorized; a separate GO is required.

## Setup order (one-time; no RunPod API POST)

1. Copy the two Python runtime scripts to `/opt/aividup-runpod-pilot/` (root-owned, 0555).
2. Install service files under `/etc/systemd/system/` and wrapper/alert scripts under
   `/usr/local/libexec/`; `systemd-analyze verify` before daemon-reload.
3. Create `/etc/aividup-runpod-pilot/` (0700, `informaten`) and its token file (0600). Generate a
   synthetic 2-second ffmpeg clip under `/var/lib/aividup-runpod-pilot/input.mp4`; this is the
   isolated job input, not production content.
4. Generate a dedicated SSH keypair under `/etc/aividup-runpod-pilot/`, create the no-shell tunnel
   account and restricted authorized-key entry, then validate `sshd -t` and effective `sshd -T`
   options. Reload SSH only after both pass.
5. Build `/etc/aividup-runpod-pilot/pod.env` (0600): isolated API URL, the plane's test bearer token,
   random worker lease/boot IDs, SSH private key in base64, pinned host-key line. Do not include
   `RUNPOD_API_KEY`.
6. Install `pod-args.json` (0644): entrypoint/cmd starts the outbound SSH tunnel, requires an HTTP 401
   response through the forwarded channel before checkpoint bootstrap, unsets key material, then
   invokes the existing bootstrap.
7. Start/enable the plane unit. Verify unauthenticated `/claim` gives 401 on host loopback and
   through the SSH forward. This does not consume the one job.
8. Install/enable the controller unit but leave `/etc/aividup-runpod-pilot/GO` **absent**. A
   `systemctl start` must be skipped by its condition and must not generate any POST. The service
   wrapper and controller resume tests cover recovery semantics.
9. Install the Hermes one-minute, no-agent alert watchdog for the `OnFailure` marker. Verify a
   temporary marker is delivered once, then clear it. No Pod is created.

## Remaining limit

The network tunnel and task URL path now both pass a real CPU-only end-to-end test. The real GPU
job has not yet completed: CUDA/RIFE preflight in run #2 is **PROBABLE_PASS** from worker control
flow, but RIFE on the two-second video, non-zero output from GPU inference, and GPU worker timings
remain **NOT TESTED**. Run #2 was the last authorized GPU rental; any further paid attempt requires
its own explicit GO. Keep `/etc/aividup-runpod-pilot/GO` absent until then.
