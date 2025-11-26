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

# Process pairs and optionally produce multiple mids per pair
imgs = sorted([p for p in os.listdir(in_dir) if p.lower().endswith('.png')])
if not os.path.exists(out_dir):
    os.makedirs(out_dir, exist_ok=True)

# Determine number of mids per pair
mids_per_pair = max(0, int(round(factor)) - 1)

total_pairs = max(0, len(imgs)-1)
print(f"Batch-runner: {len(imgs)} frames -> {total_pairs} pairs to process")
sys.stdout.flush()

for i in range(len(imgs)-1):
    a_path = os.path.join(in_dir, imgs[i])
    b_path = os.path.join(in_dir, imgs[i+1])
    try:
        im0 = cv2.imread(a_path, cv2.IMREAD_UNCHANGED)
        im1 = cv2.imread(b_path, cv2.IMREAD_UNCHANGED)
        if im0 is None or im1 is None:
            print('Failed to read input images', a_path, b_path)
            sys.stdout.flush()
            continue

        # convert to torch tensor [1,C,H,W], normalize if uint8
        # Ensure images have 3 channels; if grayscale, convert to 3-channel
        if im0.ndim == 2:
            im0 = np.stack([im0, im0, im0], axis=2)
        if im1.ndim == 2:
            im1 = np.stack([im1, im1, im1], axis=2)
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
        else:
            # generate mids at ratios k/(mids_per_pair+1)
            for k in range(1, mids_per_pair+1):
                ratio = float(k) / float(mids_per_pair + 1)
                mid = inference_with_ratio(model, t0, t1, ratio)
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