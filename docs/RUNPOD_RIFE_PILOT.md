# Runpod RIFE-only worker pilot (no production wiring)

This branch prepares a compact AIVIDUP-compatible worker image and a versioned RIFE bundle. It does not select Runpod in Laravel, create a Pod or Network Volume, call the provider API, push an image, run a GPU workload, or change production.

## Artifact contract

- Pipeline: `aividup-rife-interp-v1` (RIFE interpolation only).
- Worker code/runtime is baked under `/opt/aividup/project`; the attached Network Volume is expected at `/workspace`. Runpod documents Pod Network Volumes as replacing the default volume disk, typically mounted at `/workspace`.[1]
- Attach the Network Volume during Pod creation. The current API v2 schema requires a complete network mount (`volumeId` + `path`), allows one network mount today, and does not allow attaching/detaching or changing the volume after creation.[1][2]
- Model bundle root: `/workspace/models/rife-v4.26/`, containing only `manifest.json` and `train_log/flownet.pkl`. Model weights are excluded from the image build context and layers.
- Before worker startup, the validator opens volume files without following symlinks, verifies size/SHA from the same open file descriptor, then materializes those exact bytes into a unique `0700` scratch directory beneath `/tmp`. It creates and traverses the scratch tree relative to pinned directory FDs, uses `O_NOFOLLOW|O_EXCL`, and hashes the opened destination file after writing. RIFE loads only the verified local copy.
- `manifest.json` pins `pipeline_version`, model id, relative path, size and SHA-256. The image copies the expected manifest, verifies its hash and pipeline version at build time, stores both in OCI labels/environment, and fails before worker startup if the mounted bundle differs.
- The RIFE loader reads weights from `AIVIDUP_RIFE_MODEL_DIR` (verified scratch copy) and code from `AIVIDUP_RIFE_CODE_DIR`; the existing AIVIDUP pull-worker entrypoint and API protocol are retained.

The checked-in RIFE checkpoint is 24,636,301 bytes; the local bundle export validates against the manifest. This small RIFE-only pilot intentionally excludes Real-ESRGAN/upscaling weights and other heavy processors. It proves only the interpolation worker slice, not full AIVIDUP production capability.

## Threat model and filesystem guarantees

- **Untrusted:** the mounted Network Volume contents and its writers. Every volume path component is opened relative to a pinned directory FD with `O_NOFOLLOW`; only the expected manifest and one pinned checkpoint path are accepted. A source entry replaced before `openat` is rejected; a replacement after open cannot redirect the already-open FD.
- **Trusted:** the container image, kernel, `/` and `/tmp` directory infrastructure, and processes running under the worker's effective UID. The pilot container must not run unrelated or untrusted code under that UID. Same-UID code can bypass Unix mode bits and mutate the worker's scratch; this implementation does not claim isolation against a compromised same-UID process.
- The validator opens the trusted scratch parent once, creates a random child with `mkdirat(0700)`, checks effective-UID ownership and exact mode, and pins the child FD. All nested directory creation/open and the exclusive final-file creation are dirfd-relative and no-follow. Parent path replacement after pinning cannot redirect writes. If a nested entry is replaced by a symlink before open, the operation fails closed; if replacement occurs after opening, writes stay on the pinned directory inode.
- Destination file bytes are read back through a no-follow FD and SHA-256 checked before the validator returns. Any write/hash error removes the private scratch tree by fd-relative traversal without following symlinks. The scratch persists for the worker lifetime and is not shared across validator invocations.
- Exporter source files are walked from a pinned `/` directory FD, opening each component relative to the previously opened directory with `O_NOFOLLOW`; symlinks at any component and non-regular final files are rejected. Renaming or replacing a parent pathname after its directory FD is opened cannot redirect later opens: traversal stays on that pinned inode. The checkpoint is bounded, read once through its FD, then checked against the manifest size and SHA-256. This does not defend against a compromised same-UID process changing ordinary source files or the trusted manifest.
- These guarantees assume trusted same-UID runtime processes as stated above. Adversarial tests cover symlink swaps and concurrent destination-entry replacement, but cannot prove isolation from a compromised kernel or same-UID process.

## Build and local checks

```bash
python scripts/export_runpod_rife_bundle.py /tmp/aividup-rife-v4.26.tar.gz
./scripts/build_runpod_pilot_worker.sh
```

The exporter is deterministic and local-only. The build script builds the pilot image locally and never pushes it or creates provider resources. CI builds the pilot image for a pull request with `push: false`, reports the image byte size, and labels it with the exact PR head SHA and model-manifest hash. The candidate runtime must later be referenced by immutable image digest; a tag alone is not acceptance evidence.

## Measurement protocol

Record these separately; do not call one aggregate duration “image pull” or “worker startup”:

1. **Provision-to-container-start proxy:** record client `create-requested-at`, Runpod `createdAt`/`startedAt`, and first worker container log timestamp. Current API documentation exposes Pod lifecycle/status timestamps but does not document a dedicated Docker pull/unpack duration; report this as a provisioning/startup proxy, not pure image pull time.[2]
2. **Bundle verification/materialization:** collect `verify_materialize_seconds` from the manifest validator; it includes secure volume reads, checksum verification and copying exact bytes to scratch.
3. **RIFE model initialization:** collect `RIFE_MODEL_LOAD_SECONDS` with its `phase` (`preflight` or `worker`); the former certifies the CUDA/RIFE probe, the latter records the worker’s own load.
4. **Time to first claim:** collect existing `boot_to_claim_s` and bootstrap/claim events. In the pilot, the launcher captures `/proc/uptime` at entrypoint and the worker maps it into its monotonic clock, so this interval includes manifest materialization, CUDA/RIFE preflight and Python startup through first claim, but excludes provider provisioning/image pull.

Run first on a new Pod with the versioned volume, then create another Pod with the same volume on an independently identified different GPU host in a compatible volume location. If host identity cannot be confirmed from provider metadata, mark the cache comparison inconclusive; do not infer Network Volume benefit from a same-host Docker cache hit. Runpod documents that GPU choices depend on volume location, so both Pods must use a confirmed compatible location.[1]

The worker must use the real AIVIDUP pull protocol. The image-only CI/CPU protocol smoke does not count as a real GPU interpolation E2E. A later pilot must use an isolated, authorized test job and confirm the output file, not a demonstration script.

## Provider lifecycle, idempotency and finance gates

- The published Create Pod schema does not document an idempotency key. Treat a create timeout as ambiguous: reconcile by provider inventory and reservation identity before any retry; do not blindly repeat POST.[2]
- In API v2, the stopped-container lifecycle state is `EXITED`; `TERMINATED` means the Pod was permanently deleted. The termination endpoint describes permanently releasing compute; keep this distinct from retained volume data.[2][3]
- Network Volume data persists independently of compute; storage billing continues while an attached Pod is stopped. Current Standard storage pricing is $0.07/GB/month for the first 1 TB; actual volume size/tier and transfer costs must be confirmed before approval.[1]
- Runpod exposes separate Pod and Network Volume billing-history endpoints; the published examples return time-bucketed records/totals, but the response schemas do not specify a final-settlement marker. A terminated Pod or empty active-Pod inventory is not proof that all charges are reconciled; keep the related reservation controlled until both billing windows are reconciled.[4][5]
- Pilot completion requires: adapter/mock invariants PASS; independent review of exact SHA PASS; immutable image digest recorded; model manifest/checksums PASS; CUDA/RIFE probe PASS; one real valid output; second startup on a confirmed different host with the same volume; provider inventory confirms no live Pod; compute, volume and transfer charges reconciled with no unresolved amount.

The Runpod API adapter already present in the AIVIDUP repository is intentionally untouched in this branch. Adapter integration, production selection, any Vast fallback and any paid Runpod resource are separate later decisions. No paid GPU or Network Volume is authorized by this branch; the first bounded pilot still requires a separate financial GO.

## Sources

[1] https://docs.runpod.io/storage/network-volumes — Runpod Network Volumes
    > "Network volumes replace the Pod’s default volume disk, typically mounted at /workspace ."
    > "Network volumes must be attached during Pod deployment. They cannot be attached or detached later without deleting the Pod."
    > "Storage charges continue to accrue while the Pod is stopped, so if your balance stays at $0 and these charges can’t be covered, the network volume may eventually be terminated and its data cannot be recovered."
    > "Select a GPU type (available options depend on volume location)."
    > "Standard storage: First 1 TB : $0.07/GB/month Beyond 1 TB : $0.05/GB/month"
    > "Network volumes are only available for Pods in the Secure Cloud ."
    > "Network volumes provide persistent storage that exists independently of your compute resources."
    > "Data is retained when terminate or scale to zero."
[2] https://docs.runpod.io/api-reference-v2/pods/create-a-pod — Runpod API v2: Create a Pod
    > "EXITED — container exited (stopped) ERROR — container is in an unrecoverable error state TERMINATED — pod has been permanently deleted"
    > "Partial mounts are not supported — every mount entry must include the full schema ( size + path for persistent, volumeId + path for network)."
    > "The volumeId of a network mount is immutable; a PATCH that names a different volumeId is rejected with 400."
    > "The network field is an array for forward compatibility with eventual multi-network-volume support, but maxItems is 1 today."
[3] https://docs.runpod.io/api-reference-v2/pods/terminate-a-pod — Runpod API v2: Terminate a Pod
    > "Permanently terminate a Runpod Pod, release its compute, and understand what happens to persistent mounts, network volumes, and Cluster members."
[4] https://docs.runpod.io/api-reference-v2/billing/get-network-volume-billing-history — Runpod API v2: Network Volume Billing History
    > ""records": [ { "startTime": "2026-06-01T00:00:00Z", "endTime": "2026-06-02T00:00:00Z", "networkVolumeId": "2q9m7x4c", "totalAmount": 5.79, "standardAmount": 0, "highPerformanceAmount": 5.79 } ]"
[5] https://docs.runpod.io/api-reference-v2/billing/get-pod-billing-history — Runpod API v2: Pod Billing History
    > ""startTime" : "2026-06-01T00:00:00Z" , "endTime" : "2026-06-02T00:00:00Z" , "podId" : "7h9k2m4n6p" , "totalAmount" : 12.34 , "gpuAmount" : 11.1 , "cpuAmount" : 0 , "diskAmount" : 1.24"
