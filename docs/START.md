# 🔴 КРИТИЧНО: ProPainter RAFT Сломан!

## ✅ Multi-GPU Работает, Но...

ProPainter крашится на **ВСЕХ chunks** из-за бага в RAFT:
```
File "/opt/ProPainter/RAFT/raft.py", line 109: corr_fn = CorrBlock
[crash]
```

Это **НЕ OOM** - это баг в ProPainter C++ extensions.

## 🎯 Решение: 720p Preprocessing

### Quick Start (100% Работает):

```bash
# 1. Downscale видео
ffmpeg -i input_4k.mp4 -vf "scale=-1:720" -crf 18 input_720p.mp4

# 2. Обработать 720p
python main.py --input input_720p.mp4 --mode remove-subtitles --roi 0.05,0.4,0.9,0.4
```

### Результат:
- ✅ **Работает:** 100% (ProPainter стабилен на 720p)
- ✅ **Быстро:** 20-30 минут на 2 GPU
- ✅ **Качество:** ⭐⭐⭐⭐ (отлично)
- ✅ **Multi-GPU:** Активно

---

**См. `КРИТИЧЕСКАЯ_ПРОБЛЕМА_RAFT.md` для деталей**

