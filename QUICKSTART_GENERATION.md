# 🚀 Quick Start: Video Generation Module

## Для разработчиков

### 1. Проверка без GPU (локально)

```bash
# Import tests
python tests/test_generation_imports.py

# Unit tests
pytest tests/unit/services/generation/ -v

# Integration tests (с моками)
pytest tests/integration/generation/ -v

# Dry-run (валидация)
python -m src.entrypoints.run_gen \
  --job '{"prompts": ["A test"]}' \
  --dry-run
```

### 2. Docker build

```bash
# Build image
docker build -f Dockerfile.gen -t video-gen:latest .

# Run tests in Docker
chmod +x tests/docker/build_and_test_gen.sh
./tests/docker/build_and_test_gen.sh
```

### 3. Примеры (требует GPU)

```bash
# Simple example
python examples/generation/text2video_example.py

# Batch with B2
export B2_KEY="your_key"
export B2_SECRET="your_secret"
export B2_BUCKET="your_bucket"
python examples/generation/batch_example.py
```

---

## Для запуска на GPU

### Vast.ai

```bash
# 1. Найти инстанс с RTX 3090/4090 (24GB VRAM)
vastai search offers 'reliability > 0.9 gpu_ram > 24'

# 2. Создать инстанс
vastai create instance <OFFER_ID> \
  --image video-gen:latest \
  --disk 50 \
  --env B2_KEY="your_key" \
  --env B2_SECRET="your_secret" \
  --env B2_BUCKET="your_bucket"

# 3. Подключиться
vastai ssh <INSTANCE_ID>

# 4. Запустить генерацию
python -m src.entrypoints.run_gen \
  --job '{"prompts": ["A cat dancing"]}'
```

### Docker (локальный GPU)

```bash
# With B2 upload
docker run --rm --gpus all \
  -e B2_KEY="your_key" \
  -e B2_SECRET="your_secret" \
  -e B2_BUCKET="your_bucket" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["A beautiful sunset"]}'

# With model cache
docker run --rm --gpus all \
  -v $(pwd)/models:/root/.cache/huggingface \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["test"]}'
```

---

## Job Specification

### Text-to-Video

```json
{
  "prompts": ["A cat dancing", "A dog running"],
  "negative_prompt": "blurry, low quality",
  "seed": 42,
  "guidance_scale": 7.0,
  "num_inference_steps": 50,
  "num_frames": 49,
  "fps": 8,
  "output_prefix": "generated/"
}
```

### Command Line

```bash
python -m src.entrypoints.run_gen \
  --job '{
    "prompts": ["Your prompt here"],
    "guidance_scale": 6.0,
    "num_inference_steps": 50
  }'
```

---

## Environment Variables

```bash
# Generation settings
export GEN_T2V_MODEL_ID="THUDM/CogVideoX-5b"
export GEN_ENABLE_SAFETY_CHECKER="true"
export GEN_DEFAULT_GUIDANCE_SCALE="6.0"

# B2 Storage
export B2_KEY="your_application_key_id"
export B2_SECRET="your_application_key"
export B2_BUCKET="your_bucket_name"
export B2_ENDPOINT="https://s3.us-west-004.backblazeb2.com"

# Paths
export HF_HOME="/root/.cache/huggingface"
export GEN_TEMP_DIR="/tmp/generation"
```

---

## Troubleshooting

### Out of Memory (OOM)

```bash
# Enable all optimizations
export GEN_ENABLE_CPU_OFFLOAD="true"
export GEN_ENABLE_VAE_SLICING="true"
export GEN_ENABLE_TILING="true"
export GEN_USE_BFLOAT16="true"
export GEN_USE_XFORMERS="true"
```

### Slow generation

```bash
# Reduce inference steps
--job '{"prompts": ["test"], "num_inference_steps": 30}'

# Reduce frames
--job '{"prompts": ["test"], "num_frames": 25}'
```

### Model download issues

```bash
# Pre-download model
python -c "
from diffusers import CogVideoXPipeline
pipe = CogVideoXPipeline.from_pretrained('THUDM/CogVideoX-5b')
print('Model downloaded successfully')
"
```

---

## Performance

**Hardware:** RTX 4090 (24GB VRAM)
- Model load: ~30-60s (first time)
- Generation: ~50-75s per video (50 steps, 49 frames)
- VRAM usage: ~18-20GB

**Optimizations:**
- ✅ bfloat16: -30% VRAM
- ✅ xformers: -20% time
- ✅ CPU offload: Works on 24GB
- ✅ VAE slicing: Stable memory

---

## Documentation

- **Implementation Plan**: `IMPLEMENTATION_PLAN_GENERATION.md`
- **Architecture**: `ARCHITECTURE_RECOMMENDATIONS_GENERATION.md`
- **Status**: `GENERATION_COMPLETE_SUMMARY.md`
- **User Guide**: `README_GENERATION.md`
- **TODO**: `TODO_GENERATION.md`

---

## Support

**Phase 1 (Current):** Text-to-Video ✅
**Phase 2 (Planned):** Image-to-Video 📋

For issues, see logs at `/app/logs/` or use `--verbose` flag.
