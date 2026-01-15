# 🚀 Quick Start: Multi-GPU на Vast.ai

## ✅ Автоматическое Исправление Активно

Просто запусти команду - код сам исправит `CUDA_VISIBLE_DEVICES`:

```bash
python main.py --input video.mp4 --mode remove-subtitles --roi 0.05,0.4,0.9,0.4
```

## Что Увидишь

```
⚠️  Detected 2 GPUs but CUDA_VISIBLE_DEVICES=0
   Fixing to enable all 2 GPUs for parallel processing...
   ✅ Set CUDA_VISIBLE_DEVICES=0,1

🔍 GPU Detection: Found 2 CUDA device(s)
🚀 ProPainter Multi-GPU detected: 2 GPUs available
  GPU 0: NVIDIA GeForce RTX 3090 (23.6GB)
  GPU 1: NVIDIA GeForce RTX 3090 (23.6GB)
  Total VRAM: 47.2GB across 2 GPUs
  🎯 Multi-GPU parallel processing will be used
```

## Результат

- ✅ 2 GPU вместо 1
- ✅ ~2x быстрее
- ✅ Параллельная обработка chunks

## Если OOM

Используй 720p:

```bash
ffmpeg -i input.mp4 -vf "scale=-1:720" -crf 18 input_720p.mp4
python main.py --input input_720p.mp4 --mode remove-subtitles --roi 0.05,0.4,0.9,0.4
```

---

См. `ФИНАЛЬНОЕ_РЕШЕНИЕ.md` для деталей

