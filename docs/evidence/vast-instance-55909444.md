# Vast instance 55909444 evidence bundle

## Scope

Read-only evidence captured after the production E2E on October 14, 2026. No
new rental, ledger mutation, or production configuration change is part of this
bundle.

## Provider request identity

- Provider: Vast.ai
- Instance: `55909444`
- Host ID: `82884`
- GPU: `RTX 3090`
- Image: `ghcr.io/zerotouchprod/aividup-worker:2578d59dc0f8179aaea1cde434e6f1dfa2e746fb@sha256:f0bf12f71b4961c54de4b8e218ca75aa28ffdd32e1371cd1fb7aa120539279ef`
- Image source revision: `2578d59dc0f8179aaea1cde434e6f1dfa2e746fb`
- OCI platform: `linux/amd64`
- Vast `image_runtype`: `args`
- Vast `image_args`: `[]`
- Rent payload `runtype`: `args`
- Rent payload `args_str`: empty string
- Rent payload `onstart`: not sent by the production `VastGpuProvider`

## Observed lifecycle

- Provider create succeeded.
- Provider reported `actual_status=loading`.
- Provider status remained `Verifying Checksum` for the complete 900-second
  bootstrap budget.
- No worker bootstrap `started` event was observed.
- No worker bootstrap `ready` event was observed.
- No worker claim was observed.
- The worker image entrypoint was therefore not verified on this instance.
- Control plane deleted the instance and confirmed provider absence.

## Provider metrics at observation

- `disk_space`: 30.0 GB
- `disk_bw`: approximately 2216.9
- `inet_down`: approximately 905.2
- `gpu_name`: `RTX 3090`
- `cuda_max_good`: `13.0`
- `reliability2`: approximately `0.9864`
- `status_msg`: `Verifying Checksum`

## Accounting and cleanup

- Job result: failed with `provider reservation reconciled without a verified output`.
- User credits: 11 returned.
- GPU charge for this instance: 0 in the observed ledger response.
- Disk charge recorded: approximately `$0.004`.
- Active provider inventory after cleanup: 0 instances.
- The evidence does not establish registry corruption; it establishes a
  provider-side readiness stall on this host/image combination.

## OCI registry audit

For the exact digest, GHCR returned:

- manifest list digest: `sha256:f0bf12f71b4961c54de4b8e218ca75aa28ffdd32e1371cd1fb7aa120539279ef`
- linux/amd64 manifest digest: `sha256:8218e10e851e03e76fff60993ae984a33192d159293eccebb4b327725288a199`
- layers: 27
- compressed layer total: 6,154,074,806 bytes (5.731 GiB)
- OCI config digest: `sha256:458e8edcd9d6243cdeb5705564862a0e905ae747b38a9b63a13aa864e914ad86`
- all 27 layer HEAD requests: HTTP 200 with manifest-matching sizes

The OCI config entrypoint is:

```json
["/usr/bin/tini", "--", "/usr/local/bin/worker_start.sh"]
```

## Limitations

- No SSH shell was available because the instance never left `loading`.
- No GPU runtime, CUDA, RIFE, or actual video processing was reached.
- A full independent pull/unpack/run is provided by the exact-image CI gate in
  this PR; it was not possible on the Hermes host because Docker/Podman is not
  installed and the local k3s containerd socket requires root access.
