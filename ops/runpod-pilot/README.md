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
- The plane binds on the VPS-side `127.0.0.1:8099`; task input/output URLs must instead advertise
  the Pod-side forwarded endpoint `http://127.0.0.1:18099/api/worker`. Keep these addresses distinct.

## CPU-only end-to-end through the restricted SSH forward

Run `ops/runpod-pilot/cpu-ssh-forward-e2e.py` on the isolated controller host only after archiving
any prior plane evidence and ensuring port 8099 is free. It starts a fresh one-job plane, opens the
real restricted SSH local-forward (`18099 -> host loopback:8099`), and runs the real `Worker` with
`ffmpeg` plus the CPU-only `passthrough` processor. It verifies claim → input fetch/cut → PUT output
→ complete, non-zero output bytes, and the captured output SHA-256 against the plane evidence. It
makes no RunPod API call and uses no GPU. Use a new evidence path and output directory per invocation;
never reset `claims_served` on an already-used plane instance.

The unit regression test deliberately separates the server listener port from the advertised
client URL and checks both returned URLs (`input_url` and `output.url`).


## Current host state (vps1748, prepared only)

- `/opt/aividup-runpod-pilot/` contains the root-owned read-only controller and isolated-plane scripts.
- `aividup-pilot-plane.service` is enabled and running on `127.0.0.1:8099`; synthetic input is 2 seconds and all credentials/config are in `/etc/aividup-runpod-pilot/` with mode 0600/0700.
- SSH has the dedicated `aividup-pilot-tunnel` account; effective sshd policy is `AllowTcpForwarding local`, `PermitOpen 127.0.0.1:8099`, `ForceCommand /usr/sbin/nologin`, no PTY/agent/X11. The private key is only in the protected Pod env file and host config. No extra public HTTP port was opened.
- The host-side SSH tunnel was exercised through localhost: it reaches the plane, unauthenticated claims return 401, forwarding to port 22 is denied, remote forwarding is denied.
- `aividup-runpod-pilot.service` is enabled with `Restart=on-failure`, `StartLimitIntervalSec=300s`, `StartLimitBurst=5`, but `ConditionPathExists=/etc/aividup-runpod-pilot/GO` evaluates false. No GO marker, state file, or create latch exists; controller is inactive and cannot POST.
- Hermes job `aividup-runpod-pilot-teardown-alert` checks `ActiveState`, `NRestarts`, ambiguous state, heartbeat age, and the durable `OnFailure` marker every minute; empty path is silent. The manual no-GPU systemd integration test proved one restart→resume→watchdog alert while fake Pod was live, followed by fake deletion; no RunPod API call occurred.
- No RunPod resources were created. Last read-only inventory **2026-10-16 06:06 UTC**: 0 Pods, 0 Network Volumes; Secure RTX 3090 EU-CZ-1 LOW at $0.50/h. Subsequent local work used only fake provider; re-check before any separately approved launch.
- **Run #1 executed 2026-10-16 10:04:42–10:23:47 UTC** under a separate spend approval that moved to the
  documented fallback after the RTX 3090 offer vanished (RTX 4090 Secure, EU-RO-1, $0.89/h): Pod
  `kx35gksg1mtjfz`, ≈**$0.284**, `verified_absent: true`, controller exit 0, 0 Pods / 0 Network Volumes
  after. Outbound TCP/22 from the Pod **works** (62 accepted tunnel sessions); the run died on a
  host-only bootstrap path in `pod-args.json` (fixed, with a regression test — see
  `docs/RUNPOD_RIFE_PILOT_NO_VOLUME.md` §9–§10). Cuda/RIFE remains unverified on a real GPU. `GO` is
  absent again; the write-once `create-attempted` latch, `state.json`, and `run1-evidence.json` remain
  in `/var/lib/aividup-runpod-pilot/` as the audit trail.

The outbound TCP/22 question is now **answered**: the Pod reached `vps1748:22` and the restricted tunnel plus the pre-bootstrap HTTP 401 probe both worked in run #1. The first explicitly approved GPU run will still fail closed before checkpoint download if the tunnel cannot establish, and the external controller still owns the absolute 30-minute teardown deadline.

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

The SSH/tunnel itself can be verified from this host and the controller can be verified over a
local HTTP impersonator. **This does not prove RunPod's outbound TCP/22 route** without a RunPod
resource. The first authorized GPU run will perform an SSH handshake before checkpoint download;
if it fails, the external controller still deletes the Pod at the absolute deadline. If policy
requires network reachability proven *before* any GPU spend, a free CPU RunPod test would be needed,
but that is a paid provider resource and is not authorized here.
