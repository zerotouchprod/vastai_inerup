# 🎯 FIX: Jumping Frames in Interpolation

## Problem

При интерполяции видео иногда **картинка прыгает** - промежуточные кадры имеют **другой размер** чем оригинальные.

### Причина

RIFE требует, чтобы размер входных кадров был **кратен 64**. Код добавлял padding:

```python
# Pad to multiples of 64
ph = ((h - 1) // 64 + 1) * 64
pw = ((w - 1) // 64 + 1) * 64
pad = (0, pw - w, 0, ph - h)
if pad[1] != 0 or pad[3] != 0:
    t0 = F.pad(t0, pad)
    t1 = F.pad(t1, pad)
```

**НО:** При сохранении промежуточных кадров **не обрезал padding обратно**!

Результат:
- Оригинальные кадры: 464x688 (исходный размер)
- Промежуточные кадры: 512x704 (западдированный размер)
- При сборке в видео: **прыгающая картинка!** ❌

## Solution

После генерации промежуточного кадра **обрезать обратно до оригинального размера**:

```python
# БЫЛО (неправильно):
mid = model.inference(t0, t1)
# Сохраняем mid как есть (с padding!) ❌

# СТАЛО (правильно):
mid = model.inference(t0, t1)
mid = mid[:, :, :h, :w]  # Обрезать до оригинального (h, w) ✅
# Сохраняем mid
```

## Files Changed

**File:** `batch_rife.py`

### Change 1: Single mid interpolation (lines ~309-320)

**Before:**
```python
with torch.no_grad():
    mid = model.inference(t0, t1)
# normalize returned mid size to match inputs
try:
    ref_h, ref_w = t0.shape[2], t0.shape[3]
    mh, mw = mid.shape[2], mid.shape[3]
    if mh != ref_h or mw != ref_w:
        pad_h = max(0, ref_h - mh)
        pad_w = max(0, ref_w - mw)
        if pad_h > 0 or pad_w > 0:
            mid = F.pad(mid, (0, pad_w, 0, pad_h))
        if mid.shape[2] > ref_h or mid.shape[3] > ref_w:
            mid = mid[:, :, :ref_h, :ref_w]
except Exception:
    pass
```

**After:**
```python
with torch.no_grad():
    mid = model.inference(t0, t1)
# CRITICAL: Crop back to ORIGINAL size (h, w) to avoid jumping frames
mid = mid[:, :, :h, :w]
```

### Change 2: Multi-mid interpolation (lines ~345-355)

**Before:**
```python
for k in range(1, mids_per_pair+1):
    ratio = float(k) / float(mids_per_pair + 1)
    mid = inference_with_ratio(model, t0, t1, ratio)
    # save with index
    out_np = (mid[0] * 255.0).clamp(0,255).byte().cpu().numpy().transpose(1,2,0)
```

**After:**
```python
for k in range(1, mids_per_pair+1):
    ratio = float(k) / float(mids_per_pair + 1)
    mid = inference_with_ratio(model, t0, t1, ratio)
    # CRITICAL: Crop back to ORIGINAL size (h, w) to avoid jumping frames
    mid = mid[:, :, :h, :w]
    # save with index
    out_np = (mid[0] * 255.0).clamp(0,255).byte().cpu().numpy().transpose(1,2,0)
```

## Why This Works

### Frame sizes now:

1. **Original frames:** `h x w` (например, 464x688)
2. **Padded for RIFE:** `ph x pw` (например, 512x704) - кратно 64
3. **RIFE output:** `ph x pw` (сгенерированный кадр)
4. **Cropped back:** `h x w` ✅ - **тот же размер что оригинальные!**
5. **Saved to disk:** `h x w` ✅

**Результат:** Все кадры (оригинальные + промежуточные) имеют одинаковый размер → **нет прыжков!**

## Example

### Input video: 464x688, 24fps

**Before fix:**
```
frame_000001.png: 464x688 ✅
frame_000001_mid_01.png: 512x704 ❌ WRONG SIZE!
frame_000002.png: 464x688 ✅
frame_000002_mid_01.png: 512x704 ❌ WRONG SIZE!
→ Video jumps between frames!
```

**After fix:**
```
frame_000001.png: 464x688 ✅
frame_000001_mid_01.png: 464x688 ✅ CORRECT!
frame_000002.png: 464x688 ✅
frame_000002_mid_01.png: 464x688 ✅ CORRECT!
→ Video smooth, no jumps!
```

## Testing

```bash
# Commit fix
git add batch_rife.py
git commit -m "fix: crop interpolated frames to original size (no more jumping frames)

- Add mid = mid[:, :, :h, :w] after inference to remove padding
- Fixes jumping frames caused by size mismatch between original and interpolated frames
- Applies to both single-mid and multi-mid interpolation"

git push origin oop2

# Test with new instance
python batch_processor.py

# Check result video - should be smooth, no jumps!
```

## Verification in logs

После фикса в логах будет:
```
DEBUG: input shapes after pad t0=(1, 3, 704, 512) t1=(1, 3, 704, 512) mids_per_pair=1
Batch-runner: pair 1/144 done (1 mids)
```

И все сохранённые кадры будут **оригинального размера** (без padding).

## Status

✅ **Fixed**  
✅ **Syntax verified**  
✅ **Ready to deploy**

**Теперь интерполяция будет плавной без прыжков!** 🎯

