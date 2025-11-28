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
ffmpeg -version | head -n 3 || true

# Compute pad sizes (next multiple of 32) using ffprobe to avoid ffmpeg expression parsing issues
WH=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "$INFILE" 2>/dev/null || true)
ROT=$(ffprobe -v error -select_streams v:0 -show_entries stream_tags=rotate -of default=nw=1:nk=1 "$INFILE" 2>/dev/null || true)
if [ -z "$WH" ]; then
  log "WARNING: failed to read input width/height, falling back to no-pad extraction"
  PAD_W=""
  PAD_H=""
else
  WIDTH=$(echo "$WH" | cut -d'x' -f1)
  HEIGHT=$(echo "$WH" | cut -d'x' -f2)
  # If rotation is 90 or 270, swap width/height for display-oriented pad
  ROT_N=$(echo "${ROT:-}" | tr -d '\r\n')
  if [ -n "$ROT_N" ]; then
    case "$ROT_N" in
      90|270|-90|-270)
        log "Detected rotation=$ROT_N; swapping width/height for pad calculation"
        tmp="$WIDTH"; WIDTH="$HEIGHT"; HEIGHT="$tmp"
        ;;
    esac
  fi
  PAD_W=$(( ( (WIDTH + 31) / 32 ) * 32 ))
  PAD_H=$(( ( (HEIGHT + 31) / 32 ) * 32 ))
  # ensure pad is not smaller than input (safety check for odd probe results)
  if [ "$PAD_W" -lt "$WIDTH" ] || [ "$PAD_H" -lt "$HEIGHT" ]; then
    log "Computed pad (w=$PAD_W,h=$PAD_H) is smaller than input (w=$WIDTH,h=$HEIGHT); disabling pad"
    PAD_W=""
    PAD_H=""
  else
    log "input_w=$WIDTH input_h=$HEIGHT pad_w=$PAD_W pad_h=$PAD_H"
  fi
fi

# Try a simple PNG extraction first (no progress pipe). Save full log for debugging.
if [ -n "${PAD_W:-}" ] && [ -n "${PAD_H:-}" ]; then
  VF_PAD="pad=${PAD_W}:${PAD_H}"
else
  VF_PAD=""
fi

if [ -n "$VF_PAD" ]; then
  ffmpeg -y -hide_banner -loglevel info -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 -vf "$VF_PAD" -f image2 -vcodec png "$TMP_DIR/input/frame_%06d.png" >"$TMP_DIR/ff_extract.log" 2>&1 || true
else
  ffmpeg -y -hide_banner -loglevel info -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 -f image2 -vcodec png "$TMP_DIR/input/frame_%06d.png" >"$TMP_DIR/ff_extract.log" 2>&1 || true
fi
RC=${PIPESTATUS[0]:-1}
log "png extract rc=$RC; tail ff_extract.log (head 40):"
sed -n '1,40p' "$TMP_DIR/ff_extract.log" 2>/dev/null || true

# Diagnostic listing
log "Post-extract listing of $TMP_DIR/input (first 200 entries):"
ls -la "$TMP_DIR/input" | head -n 200 || true
FIRST_IMG=$(find "$TMP_DIR/input" -type f \( -iname '*.png' -o -iname '*.jpg' \) -print | head -n1 || true)
if [ -n "$FIRST_IMG" ]; then
  log "First frame: $FIRST_IMG"
  command -v file >/dev/null 2>&1 && file "$FIRST_IMG" || true
  command -v hexdump >/dev/null 2>&1 && hexdump -C -n 128 "$FIRST_IMG" | sed -n '1,20p' || true
else
  log "No image files found in $TMP_DIR/input"
fi

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
  log "No frames found from PNG extraction; attempting single-frame extraction test"
  ffmpeg -hide_banner -loglevel info -i "$INFILE" -frames:v 1 -f image2 -vcodec png "$TMP_DIR/input/frame_test_000001.png" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_test_extract.log"
  RC2=${PIPESTATUS[0]:-1}
  log "single-frame extract rc=$RC2"
  if [ -f "$TMP_DIR/input/frame_test_000001.png" ]; then
    log "Single test frame created; showing head:"; if command -v hexdump >/dev/null 2>&1; then hexdump -C -n 128 "$TMP_DIR/input/frame_test_000001.png" | sed -n '1,20p' || true; fi
  else
    log "Single-frame test did NOT create a PNG (rc=$RC2); tail of test log:"; tail -n 200 "$TMP_DIR/ff_test_extract.log" 2>/dev/null || true
  fi

  log "Attempting JPEG re-extraction (mjpeg) to avoid PNG decoder issues"
  rm -f "$TMP_DIR/input"/* || true
  if [ -n "${VF_PAD:-}" ]; then
    ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 -vf "$VF_PAD" -pix_fmt yuvj420p -f image2 -vcodec mjpeg "$TMP_DIR/input/frame_%06d.jpg" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_extract_jpg.log"
  else
    ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 -pix_fmt yuvj420p -f image2 -vcodec mjpeg "$TMP_DIR/input/frame_%06d.jpg" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_extract_jpg.log"
  fi
  RC3=${PIPESTATUS[0]:-1}
  log "jpeg extract rc=$RC3; tail of jpeg extract log:"; tail -n 200 "$TMP_DIR/ff_extract_jpg.log" 2>/dev/null || true
  COUNT=$(ls -1 "$TMP_DIR/input"/*.jpg 2>/dev/null | wc -l || true)
  log "jpeg_extracted_frames=$COUNT"
  if [ "$COUNT" -eq 0 ]; then
    log "JPEG re-extraction also produced zero files; aborting"
    tail -n 400 "$TMP_DIR/ff_extract.log" 2>/dev/null || true
    tail -n 400 "$TMP_DIR/ff_extract_jpg.log" 2>/dev/null || true
    exit 4
  fi
fi

# extract audio (optional)
(log "Extracting audio"; ffmpeg -hide_banner -loglevel info -i "$INFILE" -vn -acodec copy "$TMP_DIR/audio.aac" 2>&1) | progress_collapse | tee "$TMP_DIR/ff_audio.log"

# --- attempt batch-runner BEFORE assembly ---
# ensure REPO_DIR is set for batch runner/model lookup
REPO_DIR="/workspace/project/external/RIFE"
mkdir -p "$REPO_DIR/train_log" 2>/dev/null || true

log "GPU diagnostics (nvidia-smi and torch info)"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L || true
  nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader || true
fi
python3 - <<PY 2>/dev/null || true
import torch
print('torch_version=', getattr(torch, '__version__', 'n/a'))
print('cuda_available=', torch.cuda.is_available())
if torch.cuda.is_available():
    print('cuda_count=', torch.cuda.device_count())
    try:
        print('device_name=', torch.cuda.get_device_name(0))
    except Exception as e:
        print('device_name_error', e)
PY

log "Attempting batch-runner for RIFE (GPU accelerated if available)"
BATCH_PY="/workspace/project/batch_rife.py"
if [ -f "$BATCH_PY" ]; then
  log "Found external batch runner: $BATCH_PY"
  (export PYTHONUNBUFFERED=1; export REPO_DIR="$REPO_DIR"; python3 "$BATCH_PY" "$TMP_DIR/input" "$TMP_DIR/output" "$FACTOR") >"$TMP_DIR/batch_rife_run.log" 2>&1 &
  BATCH_PID=$!
  log "batch_rife.py started (pid=$BATCH_PID), waiting up to 600s for completion"
  WAIT_SECS=600
  for waited in $(seq 1 $WAIT_SECS); do
    sleep 1
    if ! kill -0 $BATCH_PID 2>/dev/null; then
      log "batch_rife.py exited (after $waited s)"; break
    fi
    if [ $((waited % 10)) -eq 0 ]; then
      log "waiting for batch-runner to finish ($waited/$WAIT_SECS)";
    fi
  done
  if kill -0 $BATCH_PID 2>/dev/null; then
    log "batch_rife.py still running after $WAIT_SECS s, killing"
    kill $BATCH_PID 2>/dev/null || true
  fi
  log "batch_rife log (tail 200):"
  tail -n 200 "$TMP_DIR/batch_rife_run.log" 2>/dev/null || true
  OUT_COUNT=$(ls -1 "$TMP_DIR/output"/*.png 2>/dev/null | wc -l || true)
  log "Batch-runner produced $OUT_COUNT outputs (sample): $(ls -1 "$TMP_DIR/output" 2>/dev/null | head -n 10 | tr '\n' ',' )"
  if [ "$OUT_COUNT" -gt 0 ]; then
    log "Batch-runner succeeded"
  else
    log "Batch-runner produced no outputs, will fall back to per-pair (inference_img.py)"
    # per-pair fallback: run inference_img.py with exp=1 for each pair
    RIFE_PY="/workspace/project/external/RIFE/inference_img.py"
    if [ -f "$RIFE_PY" ]; then
      log "Using per-pair inference with $RIFE_PY"
      # collect input frames sorted
      mapfile -t FRAMES < <(find "$TMP_DIR/input" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) -printf '%P\n' | sort)
      N=${#FRAMES[@]}
      log "Per-pair: discovered $N frames"
      if [ "$N" -lt 2 ]; then
        log "Not enough frames for per-pair inference: $N";
      else
        for ((i=0;i<$N-1;i++)); do
          a="$TMP_DIR/input/${FRAMES[$i]}"
          b="$TMP_DIR/input/${FRAMES[$i+1]}"
          pair_index=$((i+1))
          log "RIFE pair #$pair_index: $a $b -> $TMP_DIR/output/frame_$(printf "%06d" $pair_index)_mid.png"
          # run inference_img.py in TMP_DIR so it writes to ./output
          (cd "$TMP_DIR" && export PYTHONUNBUFFERED=1; timeout 300s python3 "$RIFE_PY" --img "$a" "$b" --exp 1 --model "$REPO_DIR/train_log") >"$TMP_DIR/rife_pair_${pair_index}.log" 2>&1 || true
          # check for expected mid (inference_img writes output/img1.png for exp=1)
          if [ -f "$TMP_DIR/output/img1.png" ]; then
            mv -f "$TMP_DIR/output/img1.png" "$TMP_DIR/output/frame_$(printf "%06d" $pair_index)_mid.png"
            log "Wrote mid for pair $pair_index"
          else
            log "No mid produced for pair $pair_index; see $TMP_DIR/rife_pair_${pair_index}.log"
            tail -n 200 "$TMP_DIR/rife_pair_${pair_index}.log" 2>/dev/null || true
          fi
        done
      fi
    else
      log "Per-pair inference script not found: $RIFE_PY"
    fi
  fi
else
  log "No external batch_rife.py found at $BATCH_PY; skipping batch-runner"
fi

# Attempt assembly: prefer filelist from TMP_DIR/output, else look for mids, else fallback
try_filelist(){
  FL="$TMP_DIR/filelist.txt"
  rm -f "$FL" || true
  for f in "$TMP_DIR/output"/*.png; do [ -f "$f" ] || continue; echo "file '$f'" >>"$FL"; done
  [ -s "$FL" ] || return 1
  log "filelist head:"; head -n 20 "$FL" || true
  if [ -f "$TMP_DIR/audio.aac" ]; then
    ffmpeg -hide_banner -loglevel info -y -framerate "$TARGET_FPS" -f concat -safe 0 -i "$FL" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
  else
    ffmpeg -hide_banner -loglevel info -y -framerate "$TARGET_FPS" -f concat -safe 0 -i "$FL" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
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

# Build interleaved filelist from input frames and mids (handles multiple mids per pair)
build_interleaved_filelist(){
  FL="$TMP_DIR/filelist.txt"
  rm -f "$FL" || true
  # collect input frames (absolute paths)
  mapfile -t IN_FRAMES < <(find "$TMP_DIR/input" -maxdepth 1 -type f \( -iname 'frame_*.png' -o -iname 'frame_*.jpg' \) -printf '%f\n' | sort)
  if [ ${#IN_FRAMES[@]} -eq 0 ]; then
    return 1
  fi
  # for each input frame, append the input frame then any mids for that pair
  for f in "${IN_FRAMES[@]}"; do
    # get the numeric index from name (assumes frame_000001.png)
    idx=$(echo "$f" | sed -E 's/[^0-9]*([0-9]{1,}).*/\1/')
    # canonical padded name
    inpath="$TMP_DIR/input/$(printf "frame_%06d" "$idx").png"
    if [ -f "$inpath" ]; then
      echo "file '$inpath'" >>"$FL"
    else
      # try jpg
      inpath_jpg="$TMP_DIR/input/$(printf "frame_%06d" "$idx").jpg"
      if [ -f "$inpath_jpg" ]; then
        echo "file '$inpath_jpg'" >>"$FL"
      fi
    fi
    # find mids for this index, sort by suffix to ensure correct order
    mapfile -t MIDS < <(ls -1 "$TMP_DIR/output"/frame_$(printf "%06d" "$idx")_mid*.png 2>/dev/null | sort || true)
    for m in "${MIDS[@]}"; do
      [ -f "$m" ] || continue
      echo "file '$m'" >>"$FL"
    done
  done
  [ -s "$FL" ] || return 1
  log "interleaved filelist head:"; head -n 40 "$FL" || true
  # Normalize images if needed: ensure consistent dimensions and pix_fmt for ffmpeg concat
  NORM_DIR="$TMP_DIR/normalized"
  mkdir -p "$NORM_DIR"
  # determine target size: prefer PAD_W/PAD_H computed earlier, else probe first input frame
  if [ -n "${PAD_W:-}" ] && [ -n "${PAD_H:-}" ]; then
    TGT_W=$PAD_W; TGT_H=$PAD_H
  else
    # probe first frame in list
    FIRST=$(head -n1 "$FL" | sed -E "s/^file '\''(.*)\''$/\1/" || true)
    if [ -n "$FIRST" ] && [ -f "$FIRST" ]; then
      read pw ph < <(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$FIRST" 2>/dev/null | awk -Fx '{print $1, $2}') || true
      TGT_W=${pw:-0}; TGT_H=${ph:-0}
    else
      TGT_W=0; TGT_H=0
    fi
  fi
  # if we lack a sensible target, skip normalization
  if [ "$TGT_W" -gt 0 ] && [ "$TGT_H" -gt 0 ]; then
    log "Normalizing images to ${TGT_W}x${TGT_H} (png, rgb24) into $NORM_DIR"
    FL_NORM="$TMP_DIR/filelist_normalized.txt"
    rm -f "$FL_NORM" || true
    while IFS= read -r line; do
      # extract path
      fpath=$(echo "$line" | sed -E "s/^file '\''(.*)\''$/\1/")
      if [ ! -f "$fpath" ]; then
        echo "file '$fpath'" >>"$FL_NORM"; continue
      fi
      base=$(basename "$fpath")
      target="$NORM_DIR/$base"
      # probe current size
      curwh=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$fpath" 2>/dev/null || true)
      if [ -z "$curwh" ]; then
        # cannot probe, copy as-is
        cp -f "$fpath" "$target"
      else
        curw=$(echo "$curwh" | cut -d'x' -f1)
        curh=$(echo "$curwh" | cut -d'x' -f2)
        if [ "$curw" -eq "$TGT_W" ] && [ "$curh" -eq "$TGT_H" ]; then
          # same size — ensure pix_fmt is rgb24 by re-encoding lightly
          ffmpeg -y -hide_banner -loglevel error -i "$fpath" -vf "scale=${TGT_W}:${TGT_H}" -pix_fmt rgb24 "$target" || cp -f "$fpath" "$target"
        else
          # scale/pad to target to preserve aspect (centered)
          ffmpeg -y -hide_banner -loglevel error -i "$fpath" -vf "scale='if(gt(a,${TGT_W}/${TGT_H}),${TGT_W},-2)':'if(gt(a,${TGT_W}/${TGT_H}),-2,${TGT_H})',pad=${TGT_W}:${TGT_H}:(ow-iw)/2:(oh-ih)/2" -pix_fmt rgb24 "$target" || cp -f "$fpath" "$target"
        fi
      fi
      echo "file '$target'" >>"$FL_NORM"
    done <"$FL"
    # replace FL with normalized list
    mv -f "$FL_NORM" "$FL"
    log "Normalized filelist head:"; head -n 40 "$FL" || true
  else
    log "Skipping normalization: unknown target size (TGT_W=$TGT_W TGT_H=$TGT_H)"
  fi
  return 0
}

# Try interleaved assembly (preferred when both input frames and mids exist)
if build_interleaved_filelist; then
  FL="$TMP_DIR/filelist.txt"
  if [ -f "$TMP_DIR/audio.aac" ]; then
    ffmpeg -hide_banner -loglevel info -y -framerate "$TARGET_FPS" -f concat -safe 0 -i "$FL" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_interleaved.log"
  else
    ffmpeg -hide_banner -loglevel info -y -framerate "$TARGET_FPS" -f concat -safe 0 -i "$FL" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_interleaved.log"
  fi
  if [ -s "$OUTFILE" ]; then
    log "assembled via interleaved filelist"
    log "OK $OUTFILE"
    exit 0
  else
    log "interleaved assembly failed, falling back to other methods"
    # Diagnostic: show ffmpeg assembly log and filelist head for debugging
    log "--- interleaved assembly diagnostics ---"
    if [ -f "$TMP_DIR/ff_assemble_interleaved.log" ]; then
      log "ffmpeg interleaved assemble log (tail 200):"
      tail -n 200 "$TMP_DIR/ff_assemble_interleaved.log" 2>/dev/null || true
    else
      log "No ffmpeg interleaved log found: $TMP_DIR/ff_assemble_interleaved.log"
    fi
    if [ -f "$TMP_DIR/filelist.txt" ]; then
      log "filelist head (first 60 lines):"
      head -n 60 "$TMP_DIR/filelist.txt" 2>/dev/null || true
      log "Probing first 20 files from filelist (ffprobe width,height,pix_fmt):"
      head -n 20 "$TMP_DIR/filelist.txt" | sed -E "s/^file '\''(.*)\''$/\1/" | while read -r f; do
        if [ -f "$f" ]; then
          echo "-- $f --"
          ffprobe -v error -select_streams v:0 -show_entries stream=width,height,pix_fmt -of default=nokey=1:noprint_wrappers=1 "$f" 2>/dev/null || echo "ffprobe failed for $f"
        else
          echo "-- missing $f --"
        fi
      done
    else
      log "No filelist.txt to inspect"
    fi
    log "--- end interleaved diagnostics ---"
  fi
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

