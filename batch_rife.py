import sys, os, traceback

in_dir = sys.argv[1]
out_dir = sys.argv[2]
factor = float(sys.argv[3])
repo = os.environ.get('REPO_DIR', '/workspace/project/external/RIFE')
# define alt_repo early so it's available for later candidate scanning
alt_repo = '/workspace/project/RIFEv4.26_0921'
# If REPO_DIR not present or empty, fallback candidate
if not repo or not os.path.isdir(repo):
    if os.path.isdir(alt_repo):
        repo = alt_repo
model_dir = os.path.join(repo, 'train_log')

# Try importing a model class from common locations — robust approach
import importlib, importlib.util
Model = None
tried_locations = []

# Helper to attempt import by dotted name (package-style)
def try_dotted(dotted):
    global Model
    tried_locations.append(f"dotted:{dotted}")
    try:
        mod = importlib.import_module(dotted)
        if hasattr(mod, 'Model'):
            Model = getattr(mod, 'Model')
            return True
    except Exception:
        return False
    return False

# Ensure model_dir and repo are on sys.path to help package-relative imports inside model files
try:
    if model_dir and os.path.isdir(model_dir) and model_dir not in sys.path:
        sys.path.insert(0, model_dir)
        tried_locations.append(f"sys.path-added:{model_dir}")
    if repo and os.path.isdir(repo) and repo not in sys.path:
        sys.path.insert(0, repo)
        tried_locations.append(f"sys.path-added:{repo}")
except Exception:
    pass

# Helper to attempt import by file path
def try_path(path):
    global Model
    tried_locations.append(f"file:{path}")
    if not os.path.isfile(path):
        return False
    try:
        name = f"rife_model_{abs(hash(path))}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception as e:
                # record exception for diagnostics
                tried_locations.append(f"file_error:{path}:{type(e).__name__}:{str(e)[:200]}")
                return False
            if hasattr(mod, 'Model'):
                Model = getattr(mod, 'Model')
                tried_locations.append(f"file_ok:{path}")
                return True
    except Exception as e:
        tried_locations.append(f"file_error:{path}:{type(e).__name__}:{str(e)[:200]}")
        return False
    return False

# 1) Try common dotted imports (may succeed if repo is on sys.path and packages are present)
# Add repo and repo parent to sys.path to increase chance of package imports working
candidates_sys_paths = [repo, os.path.dirname(repo), os.path.join(repo, '..')]
for p in candidates_sys_paths:
    if p and os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)
        tried_locations.append(f"sys.path-added:{p}")

# Package-style attempts (original fallback order)
if try_dotted('train_log.RIFE_HDv3'):
    pass
elif try_dotted('model.RIFE'):
    pass
elif try_dotted('train_log.RIFE_HD'):
    pass

# 2) If still not found, try file-based imports from several likely locations
if Model is None:
    # build list of candidate files
    cand_files = [
        os.path.join(repo, 'train_log', 'RIFE_HDv3.py'),
        os.path.join(repo, 'model', 'RIFE.py'),
        os.path.join(repo, 'train_log', 'RIFE_HD.py'),
        os.path.join(repo, 'RIFE_HDv3.py'),
        os.path.join(repo, 'model.py'),
    ]
    # Also check common fallback repo inside project
    alt_repo = '/workspace/project/RIFEv4.26_0921'
    if alt_repo != repo and os.path.isdir(alt_repo):
        cand_files.extend([
            os.path.join(alt_repo, 'train_log', 'RIFE_HDv3.py'),
            os.path.join(alt_repo, 'model', 'RIFE.py'),
            os.path.join(alt_repo, 'train_log', 'RIFE_HD.py'),
            os.path.join(alt_repo, 'RIFE_HDv3.py'),
        ])

    for p in cand_files:
        if try_path(p):
            break

# broaden search: look for likely model files under repo and common subdirs
if Model is None:
    def scan_for_candidates(base_dirs, name_hint_patterns=('rife','model')):
        cand = []
        for base in base_dirs:
            if not base or not os.path.isdir(base):
                continue
            # prioritize train_log and model subdirs
            for sub in ('train_log','model',''):
                d = os.path.join(base, sub) if sub else base
                if not os.path.isdir(d):
                    continue
                try:
                    for fname in sorted(os.listdir(d)):
                        lf = fname.lower()
                        if not lf.endswith('.py'):
                            continue
                        # prefer files that contain hint words
                        for pat in name_hint_patterns:
                            if pat in lf:
                                cand.append(os.path.join(d, fname))
                                break
                        else:
                            # also keep generic python files as lower priority
                            cand.append(os.path.join(d, fname))
                except Exception:
                    continue
        # dedupe while preserving order
        seen=set(); out=[]
        for p in cand:
            if p not in seen:
                seen.add(p); out.append(p)
        return out

    extra_bases = [repo, os.path.join(repo,'model'), os.path.join(repo,'train_log')]
    if alt_repo and alt_repo != repo:
        extra_bases.extend([alt_repo, os.path.join(alt_repo,'model'), os.path.join(alt_repo,'train_log')])
    candidates = scan_for_candidates(extra_bases)
    # attempt imports on candidate files
    for p in candidates:
        if try_path(p):
            break

# Final diagnostics if still not found
if Model is None:
    print('No compatible RIFE Model class found (tried train_log.RIFE_HDv3, model.RIFE, train_log.RIFE_HD)')
    print('DEBUG: REPO_DIR scanned:', repo)
    print('DEBUG: model_dir:', model_dir)
    print('DEBUG: attempted locations:')
    for t in tried_locations[-500:]:
        print('  -', t)
    # Show top-level listing of repo for debugging
    try:
        print('DEBUG: repo listing (top 50):')
        for root, dirs, files in os.walk(repo):
            print('  dir:', root)
            for f in files[:50]:
                if f.endswith('.py'):
                    print('    file:', f)
            break
    except Exception:
        pass
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

        # Normalize and convert image dtypes robustly.
        # Cases handled:
        #  - uint16 (common when ffmpeg outputs 16-bit PNG): scale down by 256 -> uint8
        #  - float32/float64 in [0,1] or [0,255]: normalize to float32 [0,1]
        #  - int types >8-bit: clamp/scale to uint8
        def normalize_img(img):
            if img.dtype == np.uint8:
                return img
            if img.dtype == np.uint16:
                # downscale 16-bit -> 8-bit
                return (img // 256).astype(np.uint8)
            if img.dtype in (np.float32, np.float64):
                # assume floats in [0,1] or [0,255]
                mx = img.max() if img.size>0 else 1.0
                if mx <= 1.0:
                    return (np.clip(img, 0.0, 1.0) * 255.0).astype(np.uint8)
                else:
                    return (np.clip(img, 0.0, 255.0)).astype(np.uint8)
            # other integer types (int16, int32, etc.) - coerce to uint8 via clipping/scaling
            if np.issubdtype(img.dtype, np.signedinteger) or np.issubdtype(img.dtype, np.integer):
                # clip to [0,255]
                return np.clip(img, 0, 255).astype(np.uint8)
            # fallback: convert to uint8 via scaling
            try:
                return img.astype(np.uint8)
            except Exception:
                return (np.clip(img, 0, 255)).astype(np.uint8)

        im0 = normalize_img(im0)
        im1 = normalize_img(im1)

        # Create torch tensors [1,C,H,W] in float32 normalized to [0,1]
        t0 = torch.from_numpy(im0.transpose(2,0,1)).unsqueeze(0).float() / 255.0
        t1 = torch.from_numpy(im1.transpose(2,0,1)).unsqueeze(0).float() / 255.0

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

# After discovery, print which method succeeded for debugging
found_source = None
for t in reversed(tried_locations):
    if t.startswith('file_ok:'):
        found_source = t.split(':',1)[1]
        break
    if t.startswith('dotted:'):
        found_source = t
        break
if found_source:
    print('DEBUG: Loaded RIFE Model from:', found_source)
else:
    # If Model exists but we don't have a recorded source, try to get module name
    try:
        mod_name = getattr(Model, '__module__', None)
        print('DEBUG: Loaded RIFE Model module:', mod_name)
    except Exception:
        pass

sys.exit(0)