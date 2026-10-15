# RTX 3090 RunPod RIFE pilot — prepared, not launched

## Scope and safety

- One RTX 3090 Secure Pod, preferred placement `EU-CZ-1`; no Network Volume, retries = 0.
- No Pod or other paid RunPod resource may be created until separately approved.
- Image startup downloads the pinned checkpoint to a fresh `0700` directory on ephemeral container storage, validates bytes, then hands off to the existing `/opt/aividup/worker_start.sh` with `AIVIDUP_MODEL_VOLUME_ROOT` overridden. `AIVIDUP_MODEL_MANIFEST_REQUIRED=1` remains enforced; worker_start runs the existing strict manifest validator before accepting work.
- No production job endpoint/token is included in the image. A dedicated isolated test control-plane/job and approved test input are required before a real render; a dry run is not a render.

## Immutable model source

- GitHub Release asset ID `644883676` in public repository `zerotouchprod/vastai_inerup`; retrieval endpoint: `https://api.github.com/repos/zerotouchprod/vastai_inerup/releases/assets/644883676` with `Accept: application/octet-stream`.
- Release tag: `rife-v4.26-checkpoint-sha256-45c7f74156704769dc9f85cfcaf8552e1e926f9399dcfa3a553dee88fac6f53f`.
- The source is an asset-ID URL rather than the mismatching upstream Google Drive link. Download redirects remain HTTPS and payload SHA/size are independently checked, so replacement/corruption fails closed.
- Checkpoint: `RIFEv4.26_0921/train_log/flownet.pkl`, 24,636,301 bytes, SHA-256 `45c7f74156704769dc9f85cfcaf8552e1e926f9399dcfa3a553dee88fac6f53f`.
- Pinned manifest SHA-256: `edcc8d3f80bb3fd8cc154903cf3e18af94309ce80ebe04eb9b9066dc8ecafa87`.

## Pod request shape (do not POST until separate GO)

Resolve `image` to the new published `...@sha256:<digest>` after build; do not use a mutable tag. Re-fetch catalog immediately before authorized launch and require a Secure RTX 3090 entry listing `EU-CZ-1`; catalog `LOW` is volatile. Suggested API v2 request shape, to be validated against the then-current schema/catalog:

```json
{
  "name": "aividup-rife-rtx3090-pilot",
  "cloud": "SECURE",
  "dataCenterIds": ["EU-CZ-1"],
  "gpu": {"id": "NVIDIA GeForce RTX 3090", "count": 1},
  "image": "ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:<new-digest>",
  "disk": 20,
  "env": {
    "AIVIDUP_MAX_RESTARTS": "0",
    "AIVIDUP_MAX_LIFETIME_SECONDS": "1800",
    "AIVIDUP_IDLE_EXIT_SECONDS": "1800",
    "AIVIDUP_MODEL_MANIFEST_REQUIRED": "1"
  }
}
```

No `mounts` property means no Network Volume. The Pod needs an isolated test worker API URL/token and one explicitly supplied safe test job; those are intentionally absent pending operational approval.

## Deadline caveat / launch gate

The inspected RunPod REST v2 `CreatePodRequest` schema has no Pod TTL/maximum-lifetime field. `AIVIDUP_MAX_LIFETIME_SECONDS=1800` limits the worker process, not the provider Pod or its billing. Therefore this request alone does **not** enforce an absolute 30-minute Pod deadline. Before any launch, an external, independently running watchdog must record the successful Pod creation time and terminate that exact Pod by `createdAt + 30 minutes`, with no create retries and a bounded API retry policy for deletion. The watchdog must remain active even if the worker/container exits. If that watchdog cannot be attached to the launch operation, NO-GO.

Before launch, also confirm current price/availability, calculate total expected cost including disk/transfer/billing granularity, and obtain separate explicit spend authorization. A `$1.25` planning target is not a provider-enforced cap.

## Verified here

- Release asset was downloaded end-to-end with HTTPS redirect; local staged bytes were `24,636,301` and SHA-256 matched exactly. No `.part` file remained; staging parent was mode `0700`.
- Bootstrap tests exercise valid install, wrong hash, incomplete transfer, HTTP failure, size limit, symlinked parent, repeated invocation, and hand-off to existing worker_start with required manifest gate.
- No image has been built or pushed yet; no Pod/volume has been created; no GPU inference or production job has run.
