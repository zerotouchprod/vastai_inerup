# Real-ESRGAN worker configuration

The native worker reads these optional environment variables. Existing defaults remain active when unset.

| Variable | Default | Meaning |
|---|---:|---|
| `REAL_ESRGAN_MODEL_X2` | `RealESRGAN_x2plus` | Model for output scale 2 |
| `REAL_ESRGAN_MODEL_X4` | `RealESRGAN_x4plus` | Model for output scale 4 |
| `REAL_ESRGAN_HALF` | `true` | Use FP16 when CUDA is available |
| `REAL_ESRGAN_TILE_SIZE` | `0` in native path | Explicit tile size; `0` disables tiling |
| `REAL_ESRGAN_BATCH_SIZE` | auto | Explicit batch size; bypasses resolution-aware selection |
| `REAL_ESRGAN_MAX_BATCH_SIZE` | auto base | Upper bound for auto batch |
| `REAL_ESRGAN_MAX_BATCH_PIXELS` | `1920*1080*base_batch` | Resolution-aware auto-batch pixel budget |

The worker refuses to replace missing `RealESRGAN_x2plus` weights with `RealESRGAN_x4plus`. A missing required model is a startup/processing error and is logged explicitly.

The runtime log includes model name, requested/network scale, input resolution, FP16, tile, tile padding, pre-padding, selected batch, and weights path. Completion logs include decode, preprocess, inference, postprocess, encode and total timings.
