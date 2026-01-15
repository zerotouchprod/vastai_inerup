#!/bin/bash
# Pre-process video to 720p for better ProPainter compatibility
# Use this if ProPainter keeps crashing on 4K videos

set -e

if [ $# -lt 2 ]; then
    echo "Usage: $0 <input_video> <output_video>"
    echo ""
    echo "Example: $0 input_4k.mp4 input_720p.mp4"
    echo ""
    echo "This downscales 4K video to 720p, making it much easier"
    echo "for ProPainter to process on 24GB GPUs."
    exit 1
fi

INPUT="$1"
OUTPUT="$2"

if [ ! -f "$INPUT" ]; then
    echo "Error: Input file not found: $INPUT"
    exit 1
fi

echo "============================================"
echo "Pre-processing Video for ProPainter"
echo "============================================"
echo "Input:  $INPUT"
echo "Output: $OUTPUT"
echo ""

# Get input resolution
INPUT_RES=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$INPUT")
echo "Input resolution: $INPUT_RES"

# Downscale to 720p height, maintaining aspect ratio
echo ""
echo "Downscaling to 720p (maintaining aspect ratio)..."
echo "Using CRF 18 (high quality) and slow preset..."

ffmpeg -i "$INPUT" \
    -vf "scale=-1:720" \
    -crf 18 \
    -preset slow \
    -c:a copy \
    "$OUTPUT"

# Get output resolution
OUTPUT_RES=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$OUTPUT")
OUTPUT_SIZE=$(du -h "$OUTPUT" | cut -f1)

echo ""
echo "============================================"
echo "✅ Pre-processing complete!"
echo "============================================"
echo "Output resolution: $OUTPUT_RES"
echo "Output size: $OUTPUT_SIZE"
echo ""
echo "Now process this file with ProPainter:"
echo "  python main.py --input \"$OUTPUT\" --mode remove-subtitles"
echo ""
echo "Expected ProPainter processing:"
echo "  • Resolution: ~405x720 (good quality)"
echo "  • Chunks: ~50-60 (manageable)"
echo "  • Time: 30-60 minutes (reasonable)"
echo "  • Quality: Good (much better than 4K→360p→4K)"

