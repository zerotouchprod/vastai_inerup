# 🐳 Docker Cleaner Image - Quick Reference

## 🚀 Quick Start

```bash
# 1. Build
./build-cleaner.sh

# 2. Test
docker run --rm video-cleaner:light python -m src.presentation.cli --help

# 3. Use
docker run --rm -v $(pwd)/input:/input -v $(pwd)/output:/output \
  video-cleaner:light \
  python -m src.presentation.cli --mode remove-subtitles --input /input/video.mp4
```

---

## 📋 Common Commands

### Subtitle Removal (Static)
```bash
docker run --rm -v $(pwd):/data video-cleaner:light \
  python -m src.presentation.cli \
  --mode remove-subtitles --input /data/video.mp4 --roi bottom
```

### Subtitle Removal (Animated - v2.1)
```bash
docker run --rm -v $(pwd):/data video-cleaner:light \
  python -m src.presentation.cli \
  --mode remove-subtitles --animated --input /data/karaoke.mp4
```

### Watermark Removal
```bash
docker run --rm -v $(pwd):/data video-cleaner:light \
  python -m src.presentation.cli \
  --mode remove-watermark --watermark-roi top-right --input /data/video.mp4
```

### Multiple Watermarks
```bash
docker run --rm -v $(pwd):/data video-cleaner:light \
  python -m src.presentation.cli \
  --mode remove-watermark --watermark-roi "top-right,bottom-left" --input /data/video.mp4
```

---

## 🎯 Key Features

- ✅ Subtitle removal (static & animated)
- ✅ Watermark removal (single & multi-ROI)
- ✅ Optical Flow (v2.1 experimental)
- ✅ Audio preservation
- ✅ 4K support (adaptive downscaling)
- ❌ No frame interpolation (RIFE excluded)
- ❌ No upscaling (Real-ESRGAN excluded)

---

## 📊 Specifications

| Metric | Value |
|--------|-------|
| **Base Image** | python:3.10-slim |
| **Size** | ~3-4GB (60% smaller) |
| **Build Time** | ~15 min (3x faster) |
| **Memory Usage** | ~1.5GB (40% less) |

---

## 🔧 Environment Variables

```bash
docker run --rm \
  -e USE_GPU=true \
  -e OPTICAL_FLOW_MAX_DIMENSION=1280 \
  -e PRESERVE_AUDIO=true \
  video-cleaner:light \
  python -m src.presentation.cli --mode remove-subtitles --input video.mp4
```

---

## 📖 Documentation

- **Full Guide:** `DOCKER_CLEANER.md`
- **Summary:** `DOCKER_CLEANER_SUMMARY.md`
- **Build Script:** `build-cleaner.sh`

---

## ✅ Validation

```bash
# Check size
docker images video-cleaner:light

# Test dependencies
docker run --rm video-cleaner:light python -c "import torch, cv2, paddleocr"

# Verify exclusions
docker run --rm video-cleaner:light python -c "from realesrgan import RealESRGANer" || echo "✅ Correctly excluded"
```

---

**Quick reference for lightweight cleaner image v2.1** 📦

