# 🔥 Real-World Torture Test - v2.1 Validation

**Purpose:** Test v2.1 Optical Flow on actual YouTube videos (not synthetic)  
**Status:** ⏳ **READY FOR EXECUTION**  
**Date:** January 3, 2026

---

## 🎯 Test Scenarios

### Scenario 1: Karaoke Video (Color Change)

**Video Type:** YouTube Karaoke  
**Expected Behavior:**
- Text color changes (white → yellow/red)
- ColorChangeDetector classifies as 'karaoke'
- Mask should adapt to color changes
- Audio preserved

**Test Command:**
```bash
python -m src.presentation.cli \
  --mode remove-subtitles \
  --animated \
  --roi bottom \
  --input karaoke_video.mp4 \
  --output output/karaoke_cleaned.mp4
```

**Validation Checklist:**
- [ ] Video downloads successfully
- [ ] Processing completes without OOM
- [ ] Text is removed (visual inspection)
- [ ] Mask "follows" color changes
- [ ] Audio is preserved
- [ ] Memory stays <2GB (1080p)

**Expected Logs:**
```
⚡ Optical flow enabled (v2.1 experimental)
AnimatedTextDetector initialized (roi=bottom, keyframe_interval=5)
Animation type detected: karaoke
Generated 150 masks via temporal propagation
```

---

### Scenario 2: TikTok/News Ticker (Moving Text)

**Video Type:** News ticker, TikTok-style moving text  
**Expected Behavior:**
- Text moves horizontally across screen
- ColorChangeDetector classifies as 'moving'
- Mask should "track" text movement
- No ghosting/trails

**Test Command:**
```bash
python -m src.presentation.cli \
  --mode remove-subtitles \
  --animated \
  --roi full \
  --input ticker_video.mp4 \
  --output output/ticker_cleaned.mp4
```

**Validation Checklist:**
- [ ] Text movement tracked smoothly
- [ ] No ghosting in cleaned video
- [ ] Classification correct ('moving')
- [ ] Speedup vs v2.0 measured

**Performance Benchmark:**
```
v2.0 (per-frame OCR): ~22.5s for 150 frames
v2.1 (optical flow):  ~10.5s for 150 frames
Expected: 2.1x speedup
```

---

### Scenario 3: 4K Video (Memory Stress Test)

**Video Type:** 4K video with subtitles  
**Expected Behavior:**
- Adaptive downscaling triggers (4K → HD)
- Memory stays <400MB (with scaling)
- Processing completes without OOM
- Quality acceptable

**Test Command:**
```bash
python -m src.presentation.cli \
  --mode remove-subtitles \
  --animated \
  --roi bottom \
  --input 4k_video.mp4 \
  --output output/4k_cleaned.mp4
```

**Memory Monitoring:**
```bash
# Monitor memory during processing
watch -n 1 'ps aux | grep python | grep -v grep | awk "{print \$6/1024\" MB\"}"'
```

**Validation Checklist:**
- [ ] Downscaling log appears: "Downscaled 3840x2160 → 1280x720"
- [ ] Memory stays <400MB (target: 150-200MB)
- [ ] Processing completes without crash
- [ ] Output quality visually acceptable
- [ ] Memory savings: 89% (1.4GB → 150MB)

**Expected Logs:**
```
OpticalFlowTracker initialized (max_dimension=1280px)
Downscaled 3840x2160 → 1280x720 for flow computation (scale=0.33, memory savings: 9.3x)
```

---

### Scenario 4: v2.0 Baseline (Compatibility)

**Video Type:** Standard video (static subtitles)  
**Expected Behavior:**
- Running WITHOUT --animated flag
- Should behave exactly like v2.0
- No optical flow initialization
- Memory baseline maintained

**Test Command:**
```bash
# NO --animated flag!
python -m src.presentation.cli \
  --mode remove-subtitles \
  --roi bottom \
  --input standard_video.mp4 \
  --output output/standard_cleaned.mp4
```

**Validation Checklist:**
- [ ] No optical flow logs
- [ ] Memory < 1.5GB (v2.0 baseline)
- [ ] Processing time similar to v2.0
- [ ] Output quality identical to v2.0

**Expected Logs (should NOT appear):**
```
❌ "OpticalFlowTracker initialized"  (должно отсутствовать)
❌ "Optical flow enabled"            (должно отсутствовать)
❌ "Animation type detected"         (должно отсутствовать)
```

---

## 📊 Test Matrix

| Scenario | Video Type | --animated | Expected Classification | Memory Target | Speed Target |
|----------|------------|------------|------------------------|---------------|--------------|
| 1. Karaoke | YouTube Karaoke | ✅ Yes | `'karaoke'` | <2GB | 2.1x faster |
| 2. Ticker | News/TikTok | ✅ Yes | `'moving'` | <2GB | 2.1x faster |
| 3. 4K Stress | 4K Subtitles | ✅ Yes | Any | <400MB | Same |
| 4. Baseline | Standard Video | ❌ No | N/A | <1.5GB | v2.0 speed |

---

## 🔍 Quality Metrics

### Visual Inspection Checklist:
- [ ] Text completely removed (no artifacts)
- [ ] Background preserved (no blurring)
- [ ] No ghosting/trails from movement
- [ ] Edges sharp (not "mushy")
- [ ] Color fidelity maintained

### Performance Metrics:
```python
# Measure processing time
time_start = time.time()
# ... processing ...
time_end = time.time()
speedup = v20_time / v21_time

# Measure memory
import psutil
process = psutil.Process()
memory_mb = process.memory_info().rss / 1024 / 1024
```

### Quality Metrics (if available):
```python
from tests.utils.quality_metrics import calculate_psnr, calculate_ssim

# Compare cleaned vs reference (non-text regions)
psnr = calculate_psnr(original, cleaned)
ssim = calculate_ssim(original, cleaned)

# Targets:
# PSNR: >35dB (good), >40dB (excellent)
# SSIM: >0.95 (good), >0.98 (excellent)
```

---

## 🎬 Test Execution Procedure

### Step 1: Download Test Videos

```bash
# Install yt-dlp if needed
pip install yt-dlp

# Download karaoke video (example)
yt-dlp -f "best[height<=1080]" \
  --output "test_videos/karaoke_%(id)s.%(ext)s" \
  "https://www.youtube.com/watch?v=KARAOKE_ID"

# Download news ticker
yt-dlp -f "best[height<=1080]" \
  --output "test_videos/ticker_%(id)s.%(ext)s" \
  "https://www.youtube.com/watch?v=TICKER_ID"

# Download 4K video (short clip)
yt-dlp -f "best[height<=2160]" \
  --output "test_videos/4k_%(id)s.%(ext)s" \
  "https://www.youtube.com/watch?v=4K_ID"
```

**Recommended Test Videos:**
- Karaoke: Search "karaoke lyrics color change"
- Ticker: Search "breaking news ticker"
- 4K: Any 4K video with subtitles

---

### Step 2: Run Tests

```bash
# Create test directory
mkdir -p test_videos output

# Test 1: Karaoke
echo "=== Test 1: Karaoke ==="
python -m src.presentation.cli \
  --mode remove-subtitles \
  --animated \
  --roi bottom \
  --input test_videos/karaoke.mp4 \
  --output output/karaoke_cleaned.mp4

# Test 2: Ticker
echo "=== Test 2: Moving Ticker ==="
python -m src.presentation.cli \
  --mode remove-subtitles \
  --animated \
  --roi full \
  --input test_videos/ticker.mp4 \
  --output output/ticker_cleaned.mp4

# Test 3: 4K Stress
echo "=== Test 3: 4K Memory Stress ==="
python -m src.presentation.cli \
  --mode remove-subtitles \
  --animated \
  --roi bottom \
  --input test_videos/4k.mp4 \
  --output output/4k_cleaned.mp4

# Test 4: v2.0 Baseline
echo "=== Test 4: v2.0 Baseline (no --animated) ==="
python -m src.presentation.cli \
  --mode remove-subtitles \
  --roi bottom \
  --input test_videos/standard.mp4 \
  --output output/standard_cleaned.mp4
```

---

### Step 3: Visual Inspection

```bash
# Compare original vs cleaned
vlc test_videos/karaoke.mp4  # Original
vlc output/karaoke_cleaned.mp4  # Cleaned

# Check for:
# ✅ Text removed
# ✅ Background preserved
# ✅ Audio present
# ✅ No artifacts
```

---

### Step 4: Log Analysis

```bash
# Search for key indicators
grep -i "optical flow" logs/processing.log
grep -i "animation type" logs/processing.log
grep -i "downscaled" logs/processing.log
grep -i "memory" logs/processing.log

# Check for errors
grep -i "error\|fail\|exception" logs/processing.log
```

---

## ✅ Success Criteria

### Must Pass (P0):
- [ ] All 4 scenarios complete without crash
- [ ] Karaoke: Text removed, audio preserved
- [ ] Ticker: Movement tracked correctly
- [ ] 4K: Memory <400MB (adaptive scaling works)
- [ ] Baseline: No optical flow logs, v2.0 speed

### Should Pass (P1):
- [ ] Speedup ≥2x on animated videos
- [ ] Memory savings ≥50% on 4K
- [ ] Classification accuracy ≥60%
- [ ] PSNR >35dB in non-text regions

### Nice to Have (P2):
- [ ] Real-time processing (24fps+)
- [ ] Perfect classification (100%)
- [ ] PSNR >40dB

---

## 📝 Test Report Template

```markdown
# v2.1 Real-World Test Report

**Date:** [Date]
**Tester:** [Name]
**Environment:** [Hardware/OS]

## Test 1: Karaoke
- Video: [Link/ID]
- Duration: [Seconds]
- Processing Time: [Seconds]
- Memory Peak: [MB]
- Classification: [Type]
- Result: ✅ PASS / ❌ FAIL
- Notes: [Observations]

## Test 2: Ticker
...

## Test 3: 4K Stress
...

## Test 4: Baseline
...

## Summary
- Tests Passed: X/4
- Overall: ✅ PASS / ❌ FAIL
- Recommendation: [Approve/Revise]
```

---

## 🚀 Next Steps After Testing

### If ALL Tests Pass:
1. ✅ Mark v2.1.0-rc1 as **VALIDATED**
2. ✅ Update version to v2.1.0 (remove -rc1)
3. ✅ Create release notes
4. ✅ Build Docker image (cleaner + production)
5. ✅ Deploy to staging
6. ✅ Merge to main branch

### If Some Tests Fail:
1. ❌ Document failures
2. ❌ Create issues for bugs
3. ❌ Fix critical issues
4. ❌ Re-test
5. ❌ Keep as v2.1.0-rc2

---

**Real-world validation is the final gate before production release!** 🔥

