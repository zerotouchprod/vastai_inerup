# Scripts Directory - Slim Vast.ai Automation

## 🚀 Quick Start Scripts (NEW!)

### **run_slim_vast.py** - Main automation script
Full pipeline: upload to B2 → create Vast.ai instance → process → download result

```bash
python scripts/run_slim_vast.py \
  --input video.mp4 \
  --mode upscale \
  --scale 2 \
  --min-vram 8 \
  --max-price 0.15
```

### **quick_slim_test.py** - Fast test wrapper
Simple testing with defaults. Recommended for first run.

```bash
# Cheapest test
python scripts/quick_slim_test.py --cheap

# With your file
python scripts/quick_slim_test.py --input my_video.mp4
```

### **test_slim_setup.py** - Validate environment
Check dependencies, credentials, and connectivity.

```bash
python scripts/test_slim_setup.py
```

## 📚 Documentation

See root directory:
- **SLIM_QUICK_START.md** - Start here!
- **SLIM_VAST_USAGE.md** - Complete guide
- **CONTEXT.md** - Project history

## 📂 Other Scripts

This directory contains many helper scripts from previous iterations. The main ones you need are listed above. For details on other scripts, see CONTEXT.md.

