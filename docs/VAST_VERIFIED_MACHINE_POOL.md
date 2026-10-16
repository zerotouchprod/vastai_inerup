# Vast Verified Machine Pool v1

`config/vast_verified_machine_pool.json` is the machine certification registry. It is intentionally separate from discovery and legacy offer preferences.

## Record identity

- `machine_id` is the stable Vast machine identifier.
- `offer_id` and `instance_id` are evidence fields only and must not be used as whitelist keys.
- `status` is one of `unknown`, `probing`, `verified`, or `cooldown`.
- A `verified` record must include the worker digest, CUDA version, PyTorch version, GPU model, `last_pass_at`, evidence reference, and confirmed cleanup.

## Production fail-closed mode

Set these variables in the production process that creates Vast offers:

```text
VAST_VERIFIED_MACHINE_POOL_PATH=/workspace/project/config/vast_verified_machine_pool.json
VAST_WORKER_IMAGE_DIGEST=sha256:<exact-worker-digest>
VAST_CUDA_VERSION=12.6
VAST_PYTORCH_VERSION=2.9.1+cu126
```

When `VAST_VERIFIED_MACHINE_POOL_PATH` is set, `VastAIClient.search_offers()` filters the freshly returned offers by `machine_id` and the complete environment fingerprint. If no compatible verified machine is available, it returns no offers and never falls back to unknown machines. Missing fingerprint variables fail closed during client initialization.

Discovery tooling must use a separate registry copy or explicit discovery mode. It must not mutate this production registry or promote a record without a full smoke PASS and confirmed provider cleanup.

## Current record

Machine `18551` is `cooldown` after offer `49383451` / instance `56224313` reached `running → loading → running` without a smoke marker. The recorded charge was `$0.015`, cleanup was confirmed, and the record is not classified as hardware failure.
