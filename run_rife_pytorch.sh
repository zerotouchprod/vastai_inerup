#!/usr/bin/env bash
# Minimal robust wrapper for RIFE/ffmpeg interpolation used by pipeline.
# Keeps diagnostics and safe fallbacks (PNG->JPEG re-extract, PIL fallback, ffmpeg minterpolate fallback).

set -u

log() { echo "[$(date '+%H:%M:%S')] $*"; }
log_debug(){ [ "${VERBOSE:-0}" = "1" ] && echo "[$(date '+%H:%M:%S')] $*"; }

INFILE=${1:-}
OUTFILE=${2:-}
FACTOR=${3:-2}

if [ -z "$INFILE" ] || [ -z "$OUTFILE" ]; then
  log "Usage: $0 <input-file> <output-file> <factor:int (default 2)>"
  exit 2
fi

REPO_DIR="/workspace/project/external/RIFE"
mkdir -p "$REPO_DIR/train_log"

# Helper: collapse ffmpeg progress into one-line summaries (reads key=value from stdin)
progress_collapse(){
  python3 -u - <<'PY'
import sys,time
kv={}
order=[]
for raw in sys.stdin:
    line=raw.strip()
    if not line or '=' not in line: continue
    k,v=line.split('=',1)
    if k not in order: order.append(k)
    kv[k]=v
    if k=='progress':
        parts=[f"{k}={kv.get(k,'')}" for k in order if k!='progress']
        parts.append(f"progress={kv.get('progress','')}")
        print(f"[{time.strftime('%H:%M:%S')}] "+' '.join(parts), flush=True)
        kv.clear(); order=[]
PY
}

# portable hex head
print_hex_head(){
  local file="$1"; local n=${2:-128}
  [ -f "$file" ] || { echo "(no file $file)"; return 1; }
  if command -v hexdump >/dev/null 2>&1; then
    hexdump -C -n "$n" "$file" | sed -n '1,20p' || true; return 0
  fi
  if command -v xxd >/dev/null 2>&1; then
    xxd -l "$n" "$file" | sed -n '1,20p' || true; return 0
  fi
  python3 - <<PY 2>/dev/null || true
import sys,binascii
b=open(sys.argv[1],'rb').read(int(sys.argv[2]))
print(binascii.hexlify(b[:16]).decode())
PY "$file" "$n"
}

# try assembling frames with concat filelist
try_filelist_assembly(){
  local src_dir="$1" out_file="$2" fr="$3" flist
  flist="${TMP_DIR}/filelist.txt"
  rm -f "$flist" || true
  for f in "$src_dir"/*.png; do [ -f "$f" ] || continue; echo "file '$f'" >>"$flist"; done
  [ -s "$flist" ] || return 1
  log "Using filelist concat assembly (first lines):"; head -n 20 "$flist" || true
  if [ -f "$TMP_DIR/audio.aac" ]; then
    (ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$out_file" 2>&1 | progress_collapse) | tee "${TMP_DIR}/assemble.log"
    return ${PIPESTATUS[0]:-1}
  else
    (ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$out_file" 2>&1 | progress_collapse) | tee "${TMP_DIR}/assemble.log"
    return ${PIPESTATUS[0]:-1}
  fi
}

# create temp dir
TMP_DIR=$(mktemp -d 2>/dev/null || mktemp -d -t rife_tmp)
[ -d "$TMP_DIR" ] || { log "Failed to create tmp dir"; exit 4; }
log "Created temp directory: $TMP_DIR"
mkdir -p "$TMP_DIR/input" "$TMP_DIR/output"

# detect fps
ORIG_FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "$INFILE" 2>/dev/null | head -n1)
if [ -z "$ORIG_FPS" ]; then ORIG_FPS=24; fi
# evaluate fraction if needed
if [[ "$ORIG_FPS" == */* ]]; then ORIG_FPS=$(awk -F'/' '{print $1/$2}' <<<"$ORIG_FPS"); fi
TARGET_FPS=$(awk -v o="$ORIG_FPS" -v f="$FACTOR" 'BEGIN{printf "%g", o*f}')
log "Original FPS: $ORIG_FPS, Target FPS: $TARGET_FPS, Factor: $FACTOR"

# extract frames (PNG). Pad to multiple of 32 to be safe for models
log "Extracting frames..."
ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 \
  -vf "pad=if(mod(iw\,32),iw+(32-mod(iw\,32)),iw):if(mod(ih\,32),ih+(32-mod(ih\,32)),ih)" \
  -pix_fmt rgb24 -f image2 -vcodec png "$TMP_DIR/input/frame_%06d.png" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_extract.log"
if [ ${PIPESTATUS[0]:-1} -ne 0 ]; then
  log "ffmpeg extraction returned non-zero (see $TMP_DIR/ff_extract.log)"
fi

# wait for files
for i in {1..10}; do
  COUNT=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l || true)
  if [ "$COUNT" -gt 0 ]; then break; fi
  log "Waiting for frames to appear in $TMP_DIR/input (attempt $i): currently $COUNT files"; sleep 1
done

COUNT=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l || true)
if [ "$COUNT" -eq 0 ]; then
  log "No PNG frames found; attempting single-frame test and JPEG fallback"
  ffmpeg -hide_banner -loglevel info -i "$INFILE" -frames:v 1 -f image2 -vcodec png "$TMP_DIR/input/frame_test_000001.png" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_test_extract.log"
  if [ -f "$TMP_DIR/input/frame_test_000001.png" ]; then
    log "Test frame created"; print_hex_head "$TMP_DIR/input/frame_test_000001.png" 128
  fi
  # JPG fallback
  log "Re-extracting frames as JPEGs (fallback)"
  rm -f "$TMP_DIR/input"/*
  ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 -vf "pad=if(mod(iw\,32),iw+(32-mod(iw\,32)),iw):if(mod(ih\,32),ih+(32-mod(ih\,32)),ih)" -pix_fmt yuvj420p -f image2 -vcodec mjpeg "$TMP_DIR/input/frame_%06d.jpg" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_extract_jpg.log"
fi

# find first image
FIRST_FRAME=$(find "$TMP_DIR/input" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) -print | head -n1 || true)
if [ -n "$FIRST_FRAME" ] && [ -f "$FIRST_FRAME" ]; then
  log "Showing hex head of first frame: $FIRST_FRAME"
  print_hex_head "$FIRST_FRAME" 128
  command -v file >/dev/null 2>&1 && file "$FIRST_FRAME" || true
else
  log "No extracted frame found after attempts"
fi

# cv2 read check
if [ -n "$FIRST_FRAME" ] && [ -f "$FIRST_FRAME" ]; then
  python3 - <<PY >"$TMP_DIR/cv_read_check.log" 2>&1
import cv2,sys
p=sys.argv[1]
img=cv2.imread(p, cv2.IMREAD_UNCHANGED)
print('cv2_read_ok', img is not None)
if img is None:
    try:
        from PIL import Image
        Image.open(p)
        print('PIL_read_ok', True)
    except Exception as e:
        print('PIL_read_ok', False, 'err', str(e))
    sys.exit(2)
sys.exit(0)
PY
  if [ $? -ne 0 ]; then
    log "CV2 failed to read first frame; will ensure JPEG fallback exists"
    # if only PNGs exist, re-extract as JPEGs
    JPGCOUNT=$(ls -1 "$TMP_DIR/input"/*.jpg 2>/dev/null | wc -l || true)
    if [ "$JPGCOUNT" -eq 0 ]; then
      log "Performing JPEG re-extract"
      rm -f "$TMP_DIR/input"/*
      ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 -vf "pad=if(mod(iw\,32),iw+(32-mod(iw\,32)),iw):if(mod(ih\,32),ih+(32-mod(ih\,32)),ih)" -pix_fmt yuvj420p -f image2 -vcodec mjpeg "$TMP_DIR/input/frame_%06d.jpg" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_extract_jpg2.log"
      sleep 1
    fi
  else
    log "CV2 read test passed"
  fi
fi

# final frame count
FRAME_COUNT=$(( (ls -1 "$TMP_DIR/input"/*.png 2>/dev/null || true; ls -1 "$TMP_DIR/input"/*.jpg 2>/dev/null || true) | wc -l ))
log "Extracted $FRAME_COUNT frames"

if [ "$FRAME_COUNT" -eq 0 ]; then
  log "ERROR: No frames extracted after retries"; rm -rf "$TMP_DIR"; exit 4
fi

# Extract audio
log "Extracting audio track..."
(ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INFILE" -vn -acodec copy "$TMP_DIR/audio.aac" 2>&1 | progress_collapse) | tee "$TMP_DIR/ff_audio.log"

# Attempt to assemble frames into output via filelist
log "Attempting to assemble frames into $OUTFILE"
if try_filelist_assembly "$TMP_DIR/output" "$OUTFILE" "$TARGET_FPS"; then
  log "Assembled via filelist: $OUTFILE"
else
  # try pattern assembly (common naming frame_%06d_mid.png)
  if ls "$TMP_DIR/output"/frame_*_mid*.png 1>/dev/null 2>&1; then
    log "Assembling from batch-produced mids"
    (ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -framerate "$TARGET_FPS" -i "$TMP_DIR/output/frame_%06d_mid.png" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -i "$TMP_DIR/audio.aac" -shortest "$OUTFILE" 2>&1 | progress_collapse) | tee "$TMP_DIR/ff_batch_assemble.log"
  else
    log "No batch-produced mids found — falling back to ffmpeg minterpolate CPU method to ensure output exists"
    (ffmpeg -hide_banner -loglevel info -y -i "$INFILE" -vf "minterpolate=fps=$TARGET_FPS:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1" -pix_fmt yuv420p -c:v libx264 -crf 18 -preset medium "$OUTFILE" 2>&1 | progress_collapse) | tee "$TMP_DIR/ff_fallback_assemble.log"
  fi
fi

# verify
if [ -s "$OUTFILE" ]; then
  log "✓ Output verified: $OUTFILE (size: $(stat -c%s "$OUTFILE") bytes)"
  exit 0
else
  log "ERROR: No output produced: $OUTFILE"
  tail -n 200 "$TMP_DIR/ff_fallback_assemble.log" 2>/dev/null || true
  exit 5
fi

