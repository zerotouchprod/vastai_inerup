# Quick Start Guide: ROI-Based Subtitle & Watermark Removal

## 🚀 Quick Usage Examples

### Generate Test Images
```bash
# Create synthetic test images for validation
python generate_test_images.py

# Output: output/test_images/
#   - subtitles/subtitle_00.jpg ... subtitle_04.jpg
#   - watermarks/watermark_top-right.jpg, etc.
```

### Remove Subtitles

```bash
# Default: Bottom subtitles (most common)
python -m src.presentation.cli \
  --input video.mp4 \
  --mode remove-subtitles

# Top subtitles (anime, documentaries)
python -m src.presentation.cli \
  --input video.mp4 \
  --mode remove-subtitles \
  --roi top

# Custom ROI (bottom 15% of frame)
python -m src.presentation.cli \
  --input video.mp4 \
  --mode remove-subtitles \
  --roi "0,0.85,1.0,0.15"

# Russian subtitles
python -m src.presentation.cli \
  --input video.mp4 \
  --mode remove-subtitles \
  --subs-lang ru \
  --roi bottom
```

### Remove Watermarks

```bash
# Top-right logo (most common)
python -m src.presentation.cli \
  --input video.mp4 \
  --mode remove-watermark \
  --watermark-roi top-right

# Bottom-left channel logo
python -m src.presentation.cli \
  --input video.mp4 \
  --mode remove-watermark \
  --watermark-roi bottom-left

# Multiple watermarks (two corners)
python -m src.presentation.cli \
  --input video.mp4 \
  --mode remove-watermark \
  --watermark-roi "top-right,bottom-left"

# Center watermark
python -m src.presentation.cli \
  --input video.mp4 \
  --mode remove-watermark \
  --watermark-roi center
```

## 📍 ROI Presets

### For Subtitles (`--roi`)
- `bottom` - Bottom 45% of frame (default)
- `top` - Top 30% of frame
- `full` - Entire frame (slower, more false positives)
- `"x,y,w,h"` - Custom coordinates (0.0-1.0 ratios)

### For Watermarks (`--watermark-roi`)
- `top-left` - Top-left 20% corner
- `top-right` - Top-right 20% corner (default)
- `bottom-left` - Bottom-left 20% corner
- `bottom-right` - Bottom-right 20% corner
- `center` - Center 40% of frame
- `"preset1,preset2"` - Multiple zones (comma-separated)

## 🧪 Testing

### Run Unit Tests
```bash
# Test ROI geometry functions
pytest tests/test_roi_geometry.py -v

# Test subtitle/watermark integration
pytest tests/test_subtitle_watermark_integration.py -v

# Run all tests
pytest tests/ -v
```

### Validate Test Images
```bash
# Generate and inspect test images
python generate_test_images.py

# Check output
ls -lh output/test_images/subtitles/
ls -lh output/test_images/watermarks/
```

## ⚡ Performance Tips

### For Faster Processing
1. **Use specific ROI** instead of `full` (2-3x faster)
2. **Disable temporal validation** for static scenes (add flag if needed)
3. **Use GPU mode** for OCR (set `USE_GPU=True` in config)
4. **Batch processing** for multiple videos

### For Better Quality
1. **Use adaptive thresholding** (automatic with ROI)
2. **Enable temporal consistency** (enabled by default)
3. **Adjust dilation** if text edges remain (`--mask-dilation` parameter)
4. **Use correct language** for OCR (`--subs-lang` parameter)

## 🐛 Troubleshooting

### Subtitles Not Removed
- ✅ Check ROI covers subtitle area (`--roi bottom`)
- ✅ Try lower confidence (`--confidence 0.001`)
- ✅ Use correct language (`--subs-lang ru`)
- ✅ Check verbose logs (`--verbose`)

### Watermark Partially Remains
- ✅ Use multi-zone ROI if watermark moves
- ✅ Increase expansion (`--expansion 15`)
- ✅ Check persistence threshold works (default 0.8)
- ✅ Verify watermark is actually static

### Performance Issues
- ✅ Use ROI pre-cropping (automatic with `--roi`)
- ✅ Reduce frame resolution if possible
- ✅ Check GPU availability for OCR
- ✅ Use static detection for watermarks

### Memory Issues
- ✅ Process shorter clips (split video)
- ✅ Use ROI to reduce processing area
- ✅ Lower batch size in config
- ✅ Enable garbage collection

## 📚 Additional Resources

- **Full Report:** `docs/COMPLETE_IMPLEMENTATION_REPORT.md`
- **Technical Docs:** `docs/ROI_SUBTITLE_IMPROVEMENTS.md`
- **Architecture:** See diagrams in reports
- **API Reference:** Check docstrings in source code

## 🆘 Common Use Cases

### Case 1: YouTube Video with Bottom Subtitles
```bash
python -m src.presentation.cli \
  --input "https://youtube.com/watch?v=..." \
  --mode remove-subtitles \
  --roi bottom \
  --output cleaned_video.mp4
```

### Case 2: TV Show with Channel Logo
```bash
python -m src.presentation.cli \
  --input tv_show.mp4 \
  --mode remove-watermark \
  --watermark-roi "top-right" \
  --output cleaned_show.mp4
```

### Case 3: Movie with Multiple Watermarks
```bash
python -m src.presentation.cli \
  --input movie.mp4 \
  --mode remove-watermark \
  --watermark-roi "top-right,bottom-left,bottom-right" \
  --output cleaned_movie.mp4
```

### Case 4: Anime with Top Subtitles
```bash
python -m src.presentation.cli \
  --input anime.mp4 \
  --mode remove-subtitles \
  --roi top \
  --subs-lang ja \
  --output cleaned_anime.mp4
```

## 🎯 Best Practices

1. **Always specify ROI** for better performance
2. **Use test images** to validate before processing long videos
3. **Check logs** with `--verbose` for debugging
4. **Backup original** videos before processing
5. **Validate output** quality before deleting originals

## 📞 Support

For issues or questions:
1. Check verbose logs (`--verbose`)
2. Review error messages carefully
3. Consult technical documentation
4. Check if test images generate correctly

---

**Last Updated:** January 3, 2026  
**Version:** 2.0.0

