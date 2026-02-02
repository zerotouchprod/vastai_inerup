# 🚀 Quick Start: Video Generation

**5 минут от нуля до первого видео!**

---

## Prerequisites

- Docker с GPU support
- NVIDIA GPU с 24GB+ VRAM (RTX 3090, RTX 4090, A5000, etc.)
- Backblaze B2 credentials (опционально)

---

## Step 1: Build Docker Image

```bash
cd /home/fevr/PycharmProjects/vastai_inerup

docker build \
  -f docker/Dockerfile.gen \
  -t video-gen:latest \
  .
```

**⏱️ Время:** ~15-20 минут (модель встраивается в образ)  
**📦 Размер:** ~15GB (модель 11GB + dependencies)

---

## Step 2: Text-to-Video (простейший пример)

```bash
docker run --rm --gpus all \
  -e B2_KEY="your_key_here" \
  -e B2_SECRET="your_secret_here" \
  -e B2_BUCKET="your_bucket" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "prompts": ["A cat dancing in the rain"]
  }'
```

**🎬 Результат:**
```json
{
  "job_id": "abc123...",
  "success": true,
  "total_prompts": 1,
  "successful": 1,
  "failed": 0,
  "duration_seconds": 45.3,
  "results": [
    {
      "prompt": "A cat dancing in the rain",
      "url": "https://s3.us-west-004.backblazeb2.com/...",
      "size_bytes": 13145728,
      "success": true
    }
  ]
}
```

---

## Step 3: Image-to-Video (анимация изображения)

### Вариант A: URL изображения

```bash
docker run --rm --gpus all \
  -e B2_KEY="your_key" \
  -e B2_SECRET="your_secret" \
  -e B2_BUCKET="your_bucket" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "mode": "image2video",
    "prompts": ["Make the character wave and smile"],
    "input_images": ["https://example.com/anime_character.jpg"]
  }'
```

### Вариант B: Base64 изображение

```bash
# Преобразуем изображение в base64
IMAGE_BASE64=$(base64 -w 0 /path/to/image.jpg)

docker run --rm --gpus all \
  -e B2_KEY="your_key" \
  -e B2_SECRET="your_secret" \
  -e B2_BUCKET="your_bucket" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job "{
    \"mode\": \"image2video\",
    \"prompts\": [\"Animate this character\"],
    \"input_images\": [\"data:image/jpeg;base64,${IMAGE_BASE64}\"]
  }"
```

### Вариант C: Локальный файл (с volume mount)

```bash
docker run --rm --gpus all \
  -v /path/to/images:/images \
  -e B2_KEY="your_key" \
  -e B2_SECRET="your_secret" \
  -e B2_BUCKET="your_bucket" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "mode": "image2video",
    "prompts": ["Make it move"],
    "input_images": ["/images/character.jpg"]
  }'
```

---

## Step 4: Batch Generation (несколько промптов)

```bash
docker run --rm --gpus all \
  -e B2_KEY="your_key" \
  -e B2_SECRET="your_secret" \
  -e B2_BUCKET="your_bucket" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "prompts": [
      "A cyberpunk city at night with neon lights",
      "A peaceful sunset over mountains",
      "Underwater coral reef with colorful fish"
    ],
    "guidance_scale": 7.0,
    "num_inference_steps": 40,
    "num_frames": 49
  }'
```

**⏱️ Время:** ~40-50 секунд на видео (зависит от GPU)

---

## Step 5: Работа без B2 (local storage)

Если не нужна загрузка в облако:

```bash
docker run --rm --gpus all \
  -v $(pwd)/output:/app/output \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "prompts": ["Test video"]
  }' \
  --no-upload
```

Результат будет в `./output/`

---

## Advanced: Custom Parameters

```bash
docker run --rm --gpus all \
  -e B2_KEY="your_key" \
  -e B2_SECRET="your_secret" \
  -e B2_BUCKET="your_bucket" \
  -e GEN_DEFAULT_NUM_INFERENCE_STEPS=50 \
  -e GEN_DEFAULT_GUIDANCE_SCALE=7.5 \
  -e GEN_ENABLE_SAFETY_CHECKER=true \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "prompts": ["A detailed anime scene"],
    "negative_prompt": "blurry, low quality, distorted",
    "seed": 42,
    "guidance_scale": 8.0,
    "num_inference_steps": 60,
    "num_frames": 73,
    "fps": 12,
    "output_prefix": "custom/videos/"
  }'
```

---

## Параметры Generation Job

### Обязательные
- `prompts` - массив текстовых промптов
- `mode` - `"text2video"` (default) или `"image2video"`
- `input_images` - массив URL/base64/paths (только для I2V)

### Опциональные
- `negative_prompt` - негативный промпт (default: `null`)
- `seed` - seed для воспроизводимости (default: `null` = random)
- `guidance_scale` - сила guidance (default: `6.0`, range: `1.0-20.0`)
- `num_inference_steps` - число шагов (default: `50`, range: `10-200`)
- `num_frames` - число кадров (default: `49`, range: `1-96`)
- `fps` - FPS видео (default: `8`, range: `1-30`)
- `output_prefix` - префикс пути в storage (default: `"generated/"`)

---

## Troubleshooting

### Out of Memory
```bash
# Уменьшить num_frames или num_inference_steps
--job '{"prompts": ["test"], "num_frames": 25, "num_inference_steps": 30}'
```

### Slow Generation
```bash
# Включить дополнительные оптимизации
-e GEN_ENABLE_CPU_OFFLOAD=true \
-e GEN_ENABLE_VAE_SLICING=true \
-e GEN_ENABLE_TILING=true
```

### Model Not Found (offline mode fails)
```bash
# Убедитесь что образ собран правильно с моделью внутри
docker build -f docker/Dockerfile.gen -t video-gen:latest .
```

---

## Next Steps

1. **Читайте полный план:** [IMPLEMENTATION_PLAN_TEXT2VIDEO_I2V.md](./IMPLEMENTATION_PLAN_TEXT2VIDEO_I2V.md)
2. **Архитектура:** [README_GENERATION.md](./README_GENERATION.md)
3. **Тесты:** `tests/run_generation_tests.sh`
4. **Deployment:** Deploy на Vast.ai с этими командами

---

## Performance Tips

### Для максимальной скорости:
```bash
-e GEN_USE_XFORMERS=true \
-e GEN_USE_BFLOAT16=true \
-e GEN_ENABLE_CPU_OFFLOAD=false  # Если хватает VRAM
```

### Для минимального использования VRAM:
```bash
-e GEN_ENABLE_CPU_OFFLOAD=true \
-e GEN_ENABLE_VAE_SLICING=true \
-e GEN_ENABLE_TILING=true \
-e GEN_USE_BFLOAT16=true
```

---

**🎉 Готово! Теперь у вас есть production-ready video generation worker!**
