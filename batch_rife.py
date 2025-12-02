import sys, os, traceback

in_dir = sys.argv[1]
out_dir = sys.argv[2]
factor = float(sys.argv[3])
repo = os.environ.get('REPO_DIR', '/workspace/project/external/RIFE')
model_dir = os.path.join(repo, 'train_log')

# Try importing a model class from common locations
Model = None
try:
    from train_log.RIFE_HDv3 import Model as _Model
    Model = _Model
except Exception:
    try:
        from model.RIFE import Model as _Model
        Model = _Model
    except Exception:
        try:
            from train_log.RIFE_HD import Model as _Model
            Model = _Model
        except Exception:
            Model = None

if Model is None:
    print('No compatible RIFE Model class found (tried train_log.RIFE_HDv3, model.RIFE, train_log.RIFE_HD)')
    sys.exit(2)

import torch
from torch.nn import functional as F
import cv2
import numpy as np
import time

# instantiate and load weights
try:
    model = Model()
except Exception as e:
    print('Failed to instantiate Model:', e)
    traceback.print_exc()
    sys.exit(2)

try:
    model.load_model(model_dir, -1)
except Exception:
    try:
        model.load_model(model_dir)
    except Exception as e:
        print('Failed to load model from', model_dir, 'error:', e)
        traceback.print_exc()
        sys.exit(2)

model.eval()
try:
    model.device()
except Exception:
    pass

use_cuda = torch.cuda.is_available()
device = torch.device('cuda' if use_cuda else 'cpu')

# --- A1: print diagnostics about torch/CUDA for remote debugging ---
print(f"DEBUG: REPO_DIR={repo} model_dir={model_dir}")
print(f"DEBUG: torch_version={getattr(torch, '__version__', 'n/a')} torch_cuda_version={getattr(torch.version, 'cuda', 'n/a')} cuda_available={use_cuda}")
print(f"DEBUG: device_resolved={device}")
if use_cuda:
    try:
        dev_count = torch.cuda.device_count()
        print(f"DEBUG: cuda_device_count={dev_count}")
        for idx in range(dev_count):
            try:
                prop = torch.cuda.get_device_properties(idx)
                total_mb = getattr(prop, 'total_memory', None)
                total_mb = total_mb // 1024**2 if total_mb is not None else 'n/a'
                name = getattr(prop, 'name', 'n/a')
                sm = f"{getattr(prop, 'major', '?')}.{getattr(prop, 'minor', '?')}"
                print(f"DEBUG: cuda_device[{idx}] name={name} total_memory_MB={total_mb} sm={sm}")
            except Exception as _e2:
                print(f"DEBUG: failed to query cuda props for idx={idx}: {_e2}")
        # show memory usage summary (best-effort)
        try:
            reserved = torch.cuda.memory_reserved(0)//1024**2 if hasattr(torch.cuda, 'memory_reserved') else None
            allocated = torch.cuda.memory_allocated(0)//1024**2 if hasattr(torch.cuda, 'memory_allocated') else None
            max_alloc = torch.cuda.max_memory_allocated(0)//1024**2 if hasattr(torch.cuda, 'max_memory_allocated') else None
            print(f"DEBUG: cuda_mem_reserved_MB={reserved} allocated_MB={allocated} max_allocated_MB={max_alloc}")
        except Exception as _e3:
            print(f"DEBUG: cuda memory query failed: {_e3}")
        try:
            cudnn_ver = torch.backends.cudnn.version() if hasattr(torch.backends, 'cudnn') else 'n/a'
            print(f"DEBUG: cudnn_version={cudnn_ver}")
        except Exception:
            pass
    except Exception as _e:
        print('DEBUG: failed to query cuda device props:', _e)
else:
    print('DEBUG: CUDA not available; running on CPU')

# helper: bisection-style inference for arbitrary ratio (copied logic from inference_img.py)
def inference_with_ratio(model, img0, img1, ratio, rthreshold=0.02, rmaxcycles=12):
    # img0/img1 are torch tensors on device, shape [1,C,H,W]
    if ratio <= 0.0:
        return img0
    if ratio >= 1.0:
        return img1
    img0_ratio = 0.0
    img1_ratio = 1.0
    if ratio <= img0_ratio + rthreshold/2:
        return img0
    if ratio >= img1_ratio - rthreshold/2:
        return img1
    tmp_img0 = img0
    tmp_img1 = img1
    for _ in range(rmaxcycles):
        with torch.no_grad():
            middle = model.inference(tmp_img0, tmp_img1)
        # Ensure middle spatial dims match inputs (tmp_img0/tmp_img1) to avoid downstream mismatches
        try:
            ref_h, ref_w = tmp_img0.shape[2], tmp_img0.shape[3]
            mh, mw = middle.shape[2], middle.shape[3]
            if mh != ref_h or mw != ref_w:
                # If middle is smaller, pad; if larger, crop
                pad_h = max(0, ref_h - mh)
                pad_w = max(0, ref_w - mw)
                if pad_h > 0 or pad_w > 0:
                    # pad bottom/right
                    middle = F.pad(middle, (0, pad_w, 0, pad_h))
                if middle.shape[2] > ref_h or middle.shape[3] > ref_w:
                    middle = middle[:, :, :ref_h, :ref_w]
        except Exception:
            pass
        middle_ratio = (img0_ratio + img1_ratio) / 2.0
        if (ratio - (rthreshold/2)) <= middle_ratio <= (ratio + (rthreshold/2)):
            return middle
        if ratio > middle_ratio:
            tmp_img0 = middle
            img0_ratio = middle_ratio
        else:
            tmp_img1 = middle
            img1_ratio = middle_ratio
    # fallback: return last middle
    return middle

# discover image files (PNG/JPG/JPEG) and emit diagnostics for remote debugging
raw_files = sorted([os.path.join(in_dir, p) for p in os.listdir(in_dir) if p.lower().endswith(('.png', '.jpg', '.jpeg'))])
print(f"DEBUG: scanning input dir={in_dir} found_pngs={len(raw_files)}")
for f in raw_files[:20]:
    try:
        st = os.stat(f)
        print(f"DEBUG: file={f} size={st.st_size} mode={oct(st.st_mode)}")
    except Exception as _e:
        print(f"DEBUG: file={f} stat_failed: {_e}")

# Use just basenames for processing like original code expected
imgs = [os.path.basename(p) for p in raw_files]

if not os.path.exists(out_dir):
    os.makedirs(out_dir, exist_ok=True)

# Determine number of mids per pair
mids_per_pair = max(0, int(round(factor)) - 1)

total_pairs = max(0, len(imgs)-1)
print(f"Batch-runner: {len(imgs)} frames -> {total_pairs} pairs to process")
sys.stdout.flush()

# --- A2: start timing for ETA/rate reporting ---
start_time = time.time()
REPORT_INTERVAL = int(os.environ.get('BATCH_RATE_REPORT_INTERVAL', '5'))
_last_report_time = start_time
_last_reported_count = 0

def _format_eta(sec):
    try:
        sec = int(sec)
    except Exception:
        return '??:??:??'
    if sec < 0:
        return '??:??:??'
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def print_rate(processed):
    global _last_report_time, _last_reported_count
    now = time.time()
    elapsed = now - start_time if start_time else 0.0
    total_fps = (processed / elapsed) if elapsed > 0 else 0.0
    interval_elapsed = now - (_last_report_time or start_time)
    inst_fps = (processed - (_last_reported_count or 0)) / interval_elapsed if interval_elapsed > 0 else 0.0
    eta = int((total_pairs - processed) / total_fps) if total_fps > 0 else -1
    if use_cuda:
        try:
            reserved = torch.cuda.memory_reserved(0)//1024**2 if hasattr(torch.cuda, 'memory_reserved') else None
            allocated = torch.cuda.memory_allocated(0)//1024**2 if hasattr(torch.cuda, 'memory_allocated') else None
        except Exception:
            reserved = allocated = None
        try:
            gpu_info = []
            for idx in range(torch.cuda.device_count()):
                try:
                    p = torch.cuda.get_device_properties(idx)
                    gpu_info.append(f"{p.name}:{(p.total_memory//1024**2) if hasattr(p, 'total_memory') else 'n/a'}MB")
                except Exception:
                    pass
            gpu_info = ','.join(gpu_info) if gpu_info else 'n/a'
        except Exception:
            gpu_info = 'n/a'
    else:
        reserved = allocated = None
        gpu_info = 'n/a'

    print(f"RATE: processed={processed}/{total_pairs} elapsed_s={int(elapsed)} avg_fps={total_fps:.2f} inst_fps={inst_fps:.2f} ETA={_format_eta(eta)} reserved_MB={reserved} allocated_MB={allocated} gpus={gpu_info}")
    sys.stdout.flush()
    _last_report_time = now
    _last_reported_count = processed

# --- A2: periodic rate/ETA and memory report ---
processed = 0
for i in range(len(imgs)-1):
    a_path = os.path.join(in_dir, imgs[i])
    b_path = os.path.join(in_dir, imgs[i+1])
    try:
        # Ensure files exist and are readable before attempting to imread
        if not os.path.isfile(a_path):
            print(f"MISSING: {a_path} does not exist; listing input dir sample: {os.listdir(in_dir)[:10]}")
            sys.stdout.flush()
            continue
        if not os.path.isfile(b_path):
            print(f"MISSING: {b_path} does not exist; listing input dir sample: {os.listdir(in_dir)[:10]}")
            sys.stdout.flush()
            continue

        im0 = cv2.imread(a_path, cv2.IMREAD_UNCHANGED)
        im1 = cv2.imread(b_path, cv2.IMREAD_UNCHANGED)
        # If OpenCV cannot read the image, try a Pillow fallback (common in minimal containers)
        if im0 is None:
            try:
                from PIL import Image
                pil = Image.open(a_path).convert('RGB')
                im0 = np.array(pil)[:,:,::-1]  # PIL gives RGB, convert to BGR to match cv2's convention
                print(f"PIL_FALLBACK_OK: {a_path}")
            except Exception as e:
                print(f"CV2_IMREAD_FAILED: {a_path} returned None from cv2.imread; attempting raw-inspect; PIL failed: {e}")
                try:
                    with open(a_path, 'rb') as fh:
                        head = fh.read(128)
                    print(f"RAW_HDR({a_path}) len={len(head)} bytes header_hex={head[:16].hex()}")
                    # copy raw file for offline inspection
                    badcopy = os.path.join(out_dir, f'bad_raw_{os.path.basename(a_path)}')
                    try:
                        import shutil
                        shutil.copy2(a_path, badcopy)
                        print(f"Copied bad raw file to {badcopy}")
                    except Exception as _e:
                        print(f"Failed to copy bad raw file: {_e}")
                except Exception as _e:
                    print(f"Failed to open raw file {a_path}: {_e}")
                sys.stdout.flush()
                continue
        if im1 is None:
            try:
                from PIL import Image
                pil = Image.open(b_path).convert('RGB')
                im1 = np.array(pil)[:,:,::-1]
                print(f"PIL_FALLBACK_OK: {b_path}")
            except Exception as e:
                print(f"CV2_IMREAD_FAILED: {b_path} returned None from cv2.imread; attempting raw-inspect; PIL failed: {e}")
                try:
                    with open(b_path, 'rb') as fh:
                        head = fh.read(128)
                    print(f"RAW_HDR({b_path}) len={len(head)} bytes header_hex={head[:16].hex()}")
                    badcopy = os.path.join(out_dir, f'bad_raw_{os.path.basename(b_path)}')
                    try:
                        import shutil
                        shutil.copy2(b_path, badcopy)
                        print(f"Copied bad raw file to {badcopy}")
                    except Exception as _e:
                        print(f"Failed to copy bad raw file: {_e}")
                except Exception as _e:
                    print(f"Failed to open raw file {b_path}: {_e}")
                sys.stdout.flush()
                continue

        # convert to torch tensor [1,C,H,W], normalize if uint8
        # Ensure images have 3 channels; if grayscale, convert to 3-channel
        if im0.ndim == 2:
            im0 = np.stack([im0, im0, im0], axis=2)
        if im1.ndim == 2:
            im1 = np.stack([im1, im1, im1], axis=2)

        # Convert uint16 to uint8 if needed (FFmpeg sometimes extracts 16-bit PNGs)
        if im0.dtype == np.uint16:
            im0 = (im0 / 256).astype(np.uint8)
        if im1.dtype == np.uint16:
            im1 = (im1 / 256).astype(np.uint8)

        t0 = torch.from_numpy(im0.transpose(2,0,1)).unsqueeze(0)
        t1 = torch.from_numpy(im1.transpose(2,0,1)).unsqueeze(0)
        if t0.dtype == torch.uint8:
            t0 = t0.float() / 255.0
        if t1.dtype == torch.uint8:
            t1 = t1.float() / 255.0
        # Pad to multiples of 64 (match model expectations observed in runtime errors)
        n,c,h,w = t0.shape
        ph = ((h - 1) // 64 + 1) * 64
        pw = ((w - 1) // 64 + 1) * 64
        pad = (0, pw - w, 0, ph - h)
        if pad[1] != 0 or pad[3] != 0:
            t0 = F.pad(t0, pad)
            t1 = F.pad(t1, pad)
        t0 = t0.to(device)
        t1 = t1.to(device)
        # debug: print shapes so remote logs can capture them
        print(f"DEBUG: input shapes after pad t0={tuple(t0.shape)} t1={tuple(t1.shape)} mids_per_pair={mids_per_pair}")
        sys.stdout.flush()

        if mids_per_pair <= 0:
            try:
                with torch.no_grad():
                    mid = model.inference(t0, t1)
                # CRITICAL: Crop back to ORIGINAL size (h, w) to avoid jumping frames
                # mid might be padded size, need to crop to original dimensions
                mid = mid[:, :, :h, :w]
            except Exception:
                print('ERROR: inference call failed; tensor shapes:')
                try:
                    print(f"t0.shape={tuple(t0.shape)} t1.shape={tuple(t1.shape)}")
                except Exception:
                    pass
                traceback.print_exc()
                sys.stdout.flush()
                raise
            # save as single mid for compatibility
            try:
                out_np = (mid[0] * 255.0).clamp(0,255).byte().cpu().numpy().transpose(1,2,0)
            except Exception:
                out_np = mid[0].byte().cpu().numpy().transpose(1,2,0)
            out_path = os.path.join(out_dir, f'frame_%06d_mid.png' % (i+1))
            cv2.imwrite(out_path, out_np)
            # free memory
            del mid, out_np
            if use_cuda:
                torch.cuda.empty_cache()
            # progress
            print(f"Batch-runner: pair {i+1}/{total_pairs} done (single mid)")
            sys.stdout.flush()

            processed += 1
            if processed % REPORT_INTERVAL == 0 or processed == total_pairs:
                print_rate(processed)
        else:
            # generate mids at ratios k/(mids_per_pair+1)
            for k in range(1, mids_per_pair+1):
                ratio = float(k) / float(mids_per_pair + 1)
                mid = inference_with_ratio(model, t0, t1, ratio)
                # CRITICAL: Crop back to ORIGINAL size (h, w) to avoid jumping frames
                mid = mid[:, :, :h, :w]
                # save with index
                try:
                    out_np = (mid[0] * 255.0).clamp(0,255).byte().cpu().numpy().transpose(1,2,0)
                except Exception:
                    out_np = mid[0].byte().cpu().numpy().transpose(1,2,0)
                out_path = os.path.join(out_dir, f'frame_%06d_mid_%02d.png' % (i+1, k))
                cv2.imwrite(out_path, out_np)
                del mid, out_np
                if use_cuda:
                    torch.cuda.empty_cache()
            # progress for multi-mid case
            print(f"Batch-runner: pair {i+1}/{total_pairs} done ({mids_per_pair} mids)")
            sys.stdout.flush()

            processed += 1
            if processed % REPORT_INTERVAL == 0 or processed == total_pairs:
                print_rate(processed)

        # free per-pair tensors
        del t0, t1, im0, im1
        if use_cuda:
            torch.cuda.empty_cache()

    except Exception as e:
        # Attempt to save the offending input pair for offline debugging
        try:
            if 'im0' in locals() and 'im1' in locals():
                badbase = os.path.join(out_dir, f'bad_pair_{i+1}')
                try:
                    cv2.imwrite(badbase + '_a.png', im0)
                    cv2.imwrite(badbase + '_b.png', im1)
                    print(f"Saved bad pair to {badbase}_a.png and {badbase}_b.png")
                except Exception:
                    pass
        except Exception:
            pass
        print('Exception processing pair', a_path, b_path, '->', e)
        traceback.print_exc()
        sys.stdout.flush()

sys.exit(0)