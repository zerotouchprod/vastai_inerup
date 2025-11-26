#!/usr/bin/env bash
# Clean, minimal runner: extract frames, try assembling, fallback to ffmpeg minterpolate.
set -u

log(){ echo "[$(date '+%H:%M:%S')] $*"; }

INFILE=${1:-}
OUTFILE=${2:-}
FACTOR=${3:-2}

if [ -z "$INFILE" ] || [ -z "$OUTFILE" ]; then
  log "Usage: $0 <input-file> <output-file> <factor:int>"
  exit 2
fi

TMP_DIR=$(mktemp -d 2>/dev/null || mktemp -d -t rife_tmp)
[ -d "$TMP_DIR" ] || { log "Failed to create tmp dir"; exit 4; }
log "TMP_DIR=$TMP_DIR"
mkdir -p "$TMP_DIR/input" "$TMP_DIR/output"

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

# detect fps
FPS_FRAC=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "$INFILE" 2>/dev/null | head -n1 || true)
if [ -z "$FPS_FRAC" ]; then
  ORIG_FPS=24
else
  if echo "$FPS_FRAC" | grep -q '/'; then
    ORIG_FPS=$(awk -F'/' '{printf "%.6f", $1/$2}' <<<"$FPS_FRAC")
  else
    ORIG_FPS=$FPS_FRAC
  fi
fi
TARGET_FPS=$(awk -v o="$ORIG_FPS" -v f="$FACTOR" 'BEGIN{printf "%g", o*f}')
log "orig_fps=$ORIG_FPS target_fps=$TARGET_FPS"

# extract frames padded to 32
log "Extracting frames to $TMP_DIR/input"
ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 \
  -vf "pad=if(mod(iw\,32),iw+(32-mod(iw\,32)),iw):if(mod(ih\,32),ih+(32-mod(ih\,32)),ih)" \
  -pix_fmt rgb24 -f image2 -vcodec png "$TMP_DIR/input/frame_%06d.png" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_extract.log"

# wait for frames
for i in 1 2 3 4 5; do
  COUNT=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l || true)
  if [ "$COUNT" -gt 0 ]; then break; fi
  log "waiting for frames... attempt $i: count=$COUNT"
  sleep 1
done

COUNT=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l || true)
log "extracted_frames=$COUNT"
if [ "$COUNT" -eq 0 ]; then
  log "No frames found; aborting"
  tail -n 200 "$TMP_DIR/ff_extract.log" 2>/dev/null || true
  exit 4
fi

# extract audio (optional)
(log "Extracting audio"; ffmpeg -hide_banner -loglevel info -i "$INFILE" -vn -acodec copy "$TMP_DIR/audio.aac" 2>&1) | progress_collapse | tee "$TMP_DIR/ff_audio.log"

# Attempt assembly: prefer filelist from TMP_DIR/output, else look for mids, else fallback
try_filelist(){
  FL="$TMP_DIR/filelist.txt"
  rm -f "$FL" || true
  for f in "$TMP_DIR/output"/*.png; do [ -f "$f" ] || continue; echo "file '$f'" >>"$FL"; done
  [ -s "$FL" ] || return 1
  log "filelist head:"; head -n 20 "$FL" || true
  if [ -f "$TMP_DIR/audio.aac" ]; then
    ffmpeg -hide_banner -loglevel info -y -f concat -safe 0 -i "$FL" -framerate "$TARGET_FPS" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
  else
    ffmpeg -hide_banner -loglevel info -y -f concat -safe 0 -i "$FL" -framerate "$TARGET_FPS" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
  fi
  return ${PIPESTATUS[0]:-1}
}

# If there's a batch runner that wrote to TMP_DIR/output, try filelist assembly
if try_filelist; then
  log "assembled via filelist"
  [ -s "$OUTFILE" ] && { log "OK $OUTFILE"; exit 0; }
fi

# Try assembling mids pattern
if ls "$TMP_DIR/output"/frame_*_mid*.png 1>/dev/null 2>&1; then
  log "Assembling from mids"
  if [ -f "$TMP_DIR/audio.aac" ]; then
    ffmpeg -hide_banner -loglevel info -y -framerate "$TARGET_FPS" -i "$TMP_DIR/output/frame_%06d_mid.png" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_mid.log"
  else
    ffmpeg -hide_banner -loglevel info -y -framerate "$TARGET_FPS" -i "$TMP_DIR/output/frame_%06d_mid.png" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_mid.log"
  fi
  [ -s "$OUTFILE" ] && { log "OK $OUTFILE"; exit 0; }
fi

# Fallback: ffmpeg minterpolate CPU
log "FALLBACK: ffmpeg minterpolate -> $OUTFILE"
ffmpeg -hide_banner -loglevel info -y -i "$INFILE" -vf "minterpolate=fps=$TARGET_FPS:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1" -pix_fmt yuv420p -c:v libx264 -crf 18 -preset medium "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_fallback.log"

if [ -s "$OUTFILE" ]; then
  log "Success: $OUTFILE"
  exit 0
else
  log "Failed to produce output"
  tail -n 200 "$TMP_DIR/ff_fallback.log" 2>/dev/null || true
  exit 5
fi

