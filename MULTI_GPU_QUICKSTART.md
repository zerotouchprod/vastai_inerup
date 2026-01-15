# Multi-GPU Quick Start Guide

## 🎯 Цель
Эта инструкция поможет быстро проверить и использовать multi-GPU support.

## 📋 Требования
- 2+ NVIDIA GPU (30xx, 40xx, 50xx серии)
- CUDA 12.x или новее
- PyTorch с CUDA support

## ✅ Быстрая проверка

### 1. Проверить доступные GPU
```bash
nvidia-smi
```

Должны видеть все GPU:
```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 535.xx       Driver Version: 535.xx       CUDA Version: 12.2    |
|-------------------------------+----------------------+----------------------+
|   0  RTX 5070 Ti             Off | 00000000:01:00.0 | N/A                  |
|   1  RTX 5070 Ti             Off | 00000000:02:00.0 | N/A                  |
+-------------------------------+----------------------+----------------------+
```

### 2. Запустить тест multi-GPU
```bash
cd /apps/PycharmProjects/vastai_interup_ztp
python3 test_multigpu.py
```

Ожидаемый вывод:
```
============================================================
Multi-GPU Support Test Suite
============================================================
✅ Found 2 GPU(s)
  GPU 0: NVIDIA GeForce RTX 5070 Ti (16.0GB)
  GPU 1: NVIDIA GeForce RTX 5070 Ti (16.0GB)

============================================================
Testing RealESRGAN Multi-GPU Support
============================================================
✅ RealESRGAN initialized
   Detected GPUs: 2
   GPU devices: ['cuda:0', 'cuda:1']
   Batch size: 8
✅ Multi-GPU support: ENABLED

============================================================
Testing RIFE Multi-GPU Support
============================================================
✅ RIFE initialized
   Detected GPUs: 2
   GPU devices: [device(type='cuda', index=0), device(type='cuda', index=1)]
✅ Multi-GPU support: ENABLED

============================================================
Testing ProPainter Multi-GPU Support
============================================================
✅ ProPainter initialized
   Detected GPUs: 2
   GPU devices: ['cuda:0', 'cuda:1']
✅ Multi-GPU support: ENABLED

============================================================
Test Summary
============================================================
RealESRGAN: ✅ PASSED
RIFE: ✅ PASSED
ProPainter: ✅ PASSED
============================================================
✅ All tests passed!
🚀 Multi-GPU mode is ready! (2 GPUs detected)
   Expected speedup: ~1.8x vs single GPU
```

## 🚀 Использование

### Upscaling (автоматически использует все GPU)
```bash
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode upscale \
  --scale 2
```

### Interpolation (автоматически использует все GPU)
```bash
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode interp \
  --target-fps 60
```

### Subtitle Removal (автоматически использует все GPU)
```bash
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode remove-subtitles \
  --roi 0.05,0.4,0.9,0.5
```

### Watermark Removal (автоматически использует все GPU)
```bash
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode remove-watermark \
  --roi top-right
```

## 📊 Мониторинг GPU

### В реальном времени
```bash
# В отдельном терминале:
watch -n 1 nvidia-smi

# Или более детально:
watch -n 1 'nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv'
```

Вы должны видеть загрузку всех GPU:
```
GPU 0: 95-100% utilization, 14000MB / 16384MB
GPU 1: 95-100% utilization, 14000MB / 16384MB
```

### В логах
Ищите строки:
```
🚀 Multi-GPU detected: 2 GPUs available
🚀 Using multi-GPU processing with 2 GPUs
Workload distribution:
  GPU 0: 96 frames (0-95)
  GPU 1: 96 frames (96-191)

...

📊 Multi-GPU Summary:
   Total GPUs used: 2
   Speedup vs single GPU: ~2x
```

## 🎓 Детальная документация

- **`MULTI_GPU_COMPLETE.md`** - Полная документация всех режимов
- **`MULTIGPU_UPSCALE_SUPPORT.md`** - Детали по upscaling
- **`MULTI_GPU_ANALYSIS.md`** - Анализ и архитектура

## 🐛 Troubleshooting

### Проблема: "Only 1 GPU detected"
```bash
# Проверьте что CUDA видит все GPU:
python3 -c "import torch; print(torch.cuda.device_count())"

# Должно вывести количество GPU (например, 2)
```

### Проблема: "CUDA out of memory"
Решения:
1. Уменьшите tile_size: `--tile-size 256` или `--tile-size 128`
2. Убедитесь что используется FP16: `--half` (по умолчанию)
3. Система автоматически адаптирует batch_size

### Проблема: Используется только 1 GPU в логах
Возможные причины:
- Слишком мало кадров (RIFE требует минимум `num_gpus * 2` пар)
- Слишком мало chunks (ProPainter требует минимум `num_gpus` chunks)
- Проверьте логи на наличие warnings

## 📈 Ожидаемая производительность

| Количество GPU | Speedup | Пример (100 frames) |
|----------------|---------|---------------------|
| 1 GPU | 1.0x | 100 секунд |
| 2 GPU | ~1.8x | ~55 секунд |
| 4 GPU | ~3.5x | ~28 секунд |

## ✅ Успешная работа

После обработки вы должны увидеть:
```
============================================================
📊 GPU UTILIZATION SUMMARY
============================================================
Available GPUs: 2
  GPU 0: NVIDIA GeForce RTX 5070 Ti (16.0GB)
  GPU 1: NVIDIA GeForce RTX 5070 Ti (16.0GB)

Processor GPU Utilization:
  Upscaler (RealESRGANNativeWrapper): 2/2 GPUs used

✅ All 2 GPUs were utilized
   Expected speedup: ~2x vs single GPU
============================================================
```

## 🎉 Готово!

Теперь все режимы автоматически используют все доступные GPU для максимальной производительности! 🚀

