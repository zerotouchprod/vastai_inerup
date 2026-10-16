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
- Unit requires the isolated plane, uses the immutable image digest, `1800s` deadline, Secure RTX 4090
  EU-RO-1, 20 GB container disk, no Network Volume, and restarts cannot extend provider `createdAt + 1800s`.
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


## Current host state (vps1748, after paid runs #1–#4 and CPU-only tunnel/log-sink E2Es)

- `/opt/aividup-runpod-pilot/` contains the root-owned read-only controller, plane source, and `crash-loop-observer.py`; the systemd supervisor and `/etc/aividup-runpod-pilot/pod-args.json` are installed from source commit `15bfb95d54128253e923127c573fd13077ae3dba`. The controller code, plane code, observer, supervisor, and Pod args match their source SHA-256 values.
- `aividup-pilot-plane.service` remains active on `127.0.0.1:8099`; it advertises task URLs at `http://127.0.0.1:18099/api/worker` and persists sink payloads under `/var/lib/aividup-runpod-pilot/worker-output/`. The preserved job `pilot-3bfa9c78-e205-4eb7-b9f8-b19aa835dbb9` was consumed by run #4: one claim, one completion, zero worker failures. The active plane process uses the legacy sink schema; stage order/timing were reconstructed from authenticated `AIVIDUP_PILOT_STAGE` files.
- SSH has the dedicated `aividup-pilot-tunnel` account; effective sshd policy is `AllowTcpForwarding local`, `PermitOpen 127.0.0.1:8099`, `ForceCommand /usr/sbin/nologin`, no PTY/agent/X11. The private key remains protected. No extra public HTTP port was opened.
- The host-side SSH tunnel was exercised through localhost: it reaches the plane, unauthenticated claims return 401, forwarding to port 22 is denied, remote forwarding is denied.
- `aividup-runpod-pilot.service` is enabled but inactive; `/etc/aividup-runpod-pilot/GO` is absent, and the GO condition currently fails. Run #3 state/latch remain archived at `/var/lib/aividup-runpod-pilot/archive/host-prep-20261016T162754Z/before/`. Run #4 authorization, state/latch, plane evidence, input, worker-output, and alert markers are preserved under `/var/lib/aividup-runpod-pilot/archive/run-4-20261016T165753Z/`; canonical run #4 state and `create-attempted` remain as the audit trail. No controller unit is active.
- The source observer correctly rejects journal-read errors, but the live controller unit has `NoNewPrivileges=true`; that blocks its `sudo journalctl` and `sudo systemctl stop` calls even though those sudo commands work interactively. It emitted `OBSERVABILITY_FAILURE` and the cron alert was delivered, but it could not stop the controller. The main controller itself remained active and completed/removed the Pod; **do not start another paid run until observer supervision works under the actual unit security context**. `systemd-analyze verify` passed; it did not detect this runtime privilege interaction.
- Provider inventory after run #3: **0 Pods**. No Network Volume was requested or created; the volumes REST path returns 404 on this account/API endpoint.
- **Run #1** (2026-10-16 10:04:42–10:23:47 UTC): documented fallback RTX 4090 Secure/EU-RO-1, `$0.89/h`; Pod `kx35gksg1mtjfz`, approx **$0.284**, `verified_absent=true`. Outbound TCP/22 worked; failure was the host-only bootstrap path, since fixed (see `docs/RUNPOD_RIFE_PILOT_NO_VOLUME.md` §9–§10).
- **Run #2** (2026-10-16 11:03:23–11:06:01 UTC): one RTX 4090 Secure/EU-RO-1 Pod `sztqbrmskj4z0k`; approx **$0.039**. Tunnel and worker startup succeeded; worker claimed the one job, then input read/cut failed with `input_invalid`. Control-flow indicates **CUDA/RIFE preflight probable pass** (the worker polls only after it passes); real two-second-video RIFE/output is **not tested**. Observer stopped the controller immediately; `verified_absent=true`, inventory 0. Evidence is in `/var/lib/aividup-runpod-pilot/run2-evidence.json`, plus archived raw plane evidence at `archive/run-2/plane-evidence.json`.
- Source diagnosis: both `input_url` and `output.url` were generated from the VPS listener `127.0.0.1:8099`; the Pod-side tunnel endpoint is `127.0.0.1:18099`. Fixed in commit `7b6f602` by adding `advertised_base_url`, keeping bind/listen on 8099 and advertising 18099 for both task URLs.
- **CPU-only SSH-forward E2E after log capture** (2026-10-16 12:08 UTC): diagnostics PUT + claim → ffmpeg cut → CPU passthrough → video PUT → complete all passed; 1 claim/completion, 0 failures. Synthetic preflight log was redacted and persisted as 83 bytes, SHA-256 `40ea931eac06e95070ff7bb1c6f71b3ca81995d01b967c2c29b29dcb571b39db`; 2-second video output **35,249 bytes**, SHA-256 `8c747834ac5b4f420ff7afa25f4b188cec1b86ba0d95ba93bcbb70b46312bf0a`. Both match evidence. Durable result: `/var/lib/aividup-runpod-pilot/cpu-e2e-log-capture-2026-10-16/summary.json` and `evidence.json`.
- **Run #3** (2026-10-16 12:25:14–12:31:01 UTC): RTX 4090 Secure/EU-RO-1 Pod `j98pz0w7kbe693`; estimated cost **≈$0.08602**. Ten accepted tunnel sessions repeated every 17–18s; Pod runtime snapshot showed uptime 0 and GPU util 0. No plane evidence, diagnostic upload, claim, output, or RIFE preflight was reached. Live provider logs GET timed out. Controller was manually stopped; one DELETE, `verified_absent=true`, inventory 0. Evidence: `/var/lib/aividup-runpod-pilot/run3-evidence.json`.
- **Run #4 — first completed RIFE render** (2026-10-16, Pod created `16:46:29.810Z`): Secure RTX 4090 / EU-RO-1, Pod `xmd6q4subex8i3`, immutable image digest `sha256:c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b`. CUDA/RIFE preflight returned `ALLOW` on RTX 4090 (compute capability 8.9, Torch `2.9.1+cu126`, CUDA `12.6`, RIFE probe 3 frames). One claim/completion, zero failures. Input: 320×180, 48 frames at 24 fps, 2.000 s, SHA-256 `660612db109cfffaf2e7e6f68f5d95fde2d78a394d9ee632a0ebc45a5ce83dd2`. Output: 320×180, 95 frames at 48 fps, 1.980 s, 34,363 bytes, SHA-256 `d6d0c6dd85a9cc1f9b427c0b51b77b1a657a5d3d9297781acb3b0ec9d7660f45`; sink byte count/SHA/mode verified and adjacent interpolated frames were not duplicates. Worker timings: `boot_to_claim=3.22s`, `process=3.08s`, `work=3.37s`, `upload=0.11s`. CUDA stderr also contains non-fatal model-device introspection warnings (`Model` lacks `parameters()`); code falls back to the requested target device, and the actual interpolation completed. Controller runtime estimated from durable state mtime: `359.841s`; estimated GPU+20GB disk cost **≈$0.08923**, not an invoice. Graceful controller stop produced one DELETE and `verified_absent=true`; provider inventory is now **0 Pods**, GO removed. Full evidence: `/var/lib/aividup-runpod-pilot/archive/run-4-20261016T165753Z/`.
- Run #3 did not meet the render goal. The stderr/stdout sink itself passed a CPU E2E test, but did not receive logs because the Pod never reached the wrapped CUDA preflight. The temporary crash-loop observer used an invalid `journalctl --since` timestamp; the corrected observer, legacy-plane fallback, and current host state are documented above.
- Source records the ordered durable path `tunnel_ready → http_probe_pass → bootstrap_started → checkpoint_verified → worker_started → cuda_preflight`. Bootstrap stdout/stderr is uploaded in cleanup; CUDA/RIFE stdout/stderr is uploaded immediately before a worker can claim, with SHA-256 and mode `0600`. Missing stages have bounded observer deadlines; journal read errors write `OBSERVABILITY_FAILURE` and persist an alert marker. The observer attempts to stop the controller, but the current `NoNewPrivileges=true` unit blocks its sudo path; this host integration remains a blocker for another paid run. The observer, supervisor, and Pod args are installed; the controller is inactive and the live plane was not restarted.
- Verified CPU-image CI run [`38920937141`](https://github.com/zerotouchprod/vastai_inerup/actions/runs/38920937141) on `55f140b`: tests and exact immutable-image E2E passed with the unchanged `pod-args.json`, a restricted SSHD+plane sidecar on an isolated Docker network, and no RunPod API call, provider resource, GPU, or Network Volume. Evidence contains all six stages; the actual checkpoint bootstrap and manifest validation completed; CUDA preflight failed as expected with `cuda_unavailable`, logs were persisted/hash-checked (mode `0600` verified in-job), and `claims_served=0`. A CPU result does not certify GPU RIFE inference.
- Legacy-plane observer fallback tests passed in workflow [`38930285285`](https://github.com/zerotouchprod/vastai_inerup/actions/runs/38930285285) on `15bfb95d54128253e923127c573fd13077ae3dba`; image publishing and CPU image E2E were explicitly disabled for this tests-only run.

Run #4 proves one real 2× RIFE interpolation on the RTX 4090 for the two-second fixture; it is not a performance benchmark or broad compatibility guarantee. The Pod was deleted, inventory is zero, and the run’s GO was removed/archived. The observer’s `NoNewPrivileges` incompatibility is a blocker for any future paid attempt until fixed and tested under the real systemd unit. Recheck catalog LOW availability and registry digest immediately before any later separately approved run.

If the 4090 Pod is deleted promptly at its configured 1800-second deadline, the estimate is `$0.445` GPU plus approximately `$0.001369` container disk (20 GB, `$0.10/GB/month`, per-second billing), or about `$0.44637` total for 30 minutes using a 730.5-hour average month ([RunPod pricing](https://docs.runpod.io/pods/pricing)). RunPod pricing docs state no data ingress/egress fees. No Network Volume is requested. This is not a hard maximum: delete/teardown delay adds charges, and RunPod has no provider-enforced Pod TTL; the controller deadline is best-effort, so total exposure can exceed this estimate if controller/teardown/API recovery fails.

The exact image still installs `openssh-client` dynamically with `apt-get` at startup. CPU E2E reached the tunnel successfully, but this remains an external apt-repository dependency and has not been baked into a newly published image.

## Original setup procedure (historical reference; vps1748 already prepared)

This checklist documents the one-time isolated host setup; do not rerun it on vps1748 before another paid attempt. The plane job has been consumed, controller GO is absent, and run #4 state/evidence are archived.

1. Copy the controller, isolated-plane, and `crash-loop-observer.py` runtime scripts to `/opt/aividup-runpod-pilot/` (root-owned, 0555). The controller supervisor must launch the observer before the first create request.
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
6. Install `pod-args.json` (0644): entrypoint/cmd starts the outbound SSH tunnel, durably reports
   `tunnel_ready` and `http_probe_pass`, then `bootstrap_started`; a worker-start wrapper reports
   `checkpoint_verified`, `worker_started`, and `cuda_preflight` in order. Bootstrap stdout/stderr
   is uploaded during cleanup and CUDA/RIFE stdout/stderr before any worker claim; sink failures
   fail closed.
7. Start/enable the plane unit. Verify unauthenticated `/claim` gives 401 on host loopback and
   through the SSH forward. This does not consume the one job.
8. Install/enable the controller unit but leave `/etc/aividup-runpod-pilot/GO` **absent**. A
   `systemctl start` must be skipped by its condition and must not generate any POST. The service
   wrapper and controller resume tests cover recovery semantics.
9. Install the Hermes one-minute, no-agent alert watchdog for the `OnFailure` marker. Verify a
   temporary marker is delivered once, then clear it. No Pod is created.

## Remaining limit

CPU tunnel E2E and run #4 RIFE interpolation succeeded. GPU worker timings are available for this
single small fixture only; no general throughput claim is justified. The next paid attempt remains
blocked until the observer can read the journal and stop the controller under `NoNewPrivileges=true`
without losing the one-Pod teardown guarantee. Keep `/etc/aividup-runpod-pilot/GO` absent until that
fix is tested and a new explicit GO is given.
