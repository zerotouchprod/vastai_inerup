#!/usr/bin/env python3
"""
Batch Real-ESRGAN upscaling for efficient GPU processing
Processes multiple frames in parallel on GPU
"""
import sys
import os
import cv2
import torch
from pathlib import Path
import argparse
import time
import subprocess
import io
import contextlib
import sys as _sys
import concurrent.futures
import shutil
import uuid

LOG_PATH = '/workspace/realesrgan_diag.log'


@contextlib.contextmanager
def _suppress_prints():
    """Temporarily redirect stdout and stderr to devnull to suppress noisy library prints."""
    try:
        devnull = open('/dev/null', 'w')
    except Exception:
        devnull = io.StringIO()
    old_out, old_err = _sys.stdout, _sys.stderr
    try:
        _sys.stdout = devnull
        _sys.stderr = devnull
        yield
    finally:
        try:
            if hasattr(devnull, 'close'):
                devnull.close()
        except Exception:
            pass
        _sys.stdout, _sys.stderr = old_out, old_err


def _append_log(line: str):
    try:
        with open(LOG_PATH, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass


def print_env_info():
    """Print basic environment and GPU / library diagnostics and append to LOG_PATH."""
    lines = []
    lines.append('=== ENV DIAGNOSTICS ===')
    lines.append(f'Python: {sys.version.split()[0]} ({sys.executable})')
    # torch / cuda
    try:
        import torch
        lines.append(f'torch: {torch.__version__}')
        lines.append(f'torch.cuda.is_available: {torch.cuda.is_available()}')
        if torch.cuda.is_available():
            try:
                dev = torch.cuda.current_device()
                lines.append(f'cuda_device: {dev} {torch.cuda.get_device_name(dev)}')
                prop = torch.cuda.get_device_properties(dev)
                lines.append(f'cuda_total_mem_gb: {prop.total_memory/1024**3:.2f}')
            except Exception as e:
                lines.append(f'cuda device info failed: {e}')
    except Exception as e:
        lines.append(f'torch import failed: {e}')

    # realesrgan / basicsr versions
    try:
        import realesrgan
        lines.append(f'realesrgan: {getattr(realesrgan, "__version__", "unknown")}')
    except Exception:
        lines.append('realesrgan: not importable')
    try:
        import basicsr
        lines.append(f'basicsr: {getattr(basicsr, "__version__", "unknown")}')
    except Exception:
        lines.append('basicsr: not importable')

    # nvidia-smi snapshot
    try:
        out = subprocess.check_output(['nvidia-smi', '--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu', '--format=csv,noheader,nounits'], stderr=subprocess.STDOUT, text=True)
        lines.append('nvidia-smi:')
        for l in out.strip().splitlines():
            lines.append('  '+l)
    except Exception as e:
        lines.append(f'nvidia-smi failed: {e}')

    # write and print
    for l in lines:
        print(l)
        _append_log(l)
    _append_log('=== END ENV DIAGNOSTICS ===')
    print('Wrote diagnostics to', LOG_PATH)


# Add Real-ESRGAN to path
REALESRGAN_DIR = os.environ.get('REALESRGAN_DIR', '/workspace/project/external/Real-ESRGAN')
if not os.path.isdir(REALESRGAN_DIR):
    for alt_dir in ['./external/Real-ESRGAN', '../external/Real-ESRGAN', './Real-ESRGAN']:
        if os.path.isdir(alt_dir):
            REALESRGAN_DIR = os.path.abspath(alt_dir)
            break

if os.path.isdir(REALESRGAN_DIR):
    sys.path.insert(0, REALESRGAN_DIR)
else:
    print(f"ERROR: Real-ESRGAN directory not found: {REALESRGAN_DIR}")
    sys.exit(1)

# Import Real-ESRGAN
try:
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer
    from realesrgan.archs.srvgg_arch import SRVGGNetCompact
except ImportError as e:
    print(f"ERROR: Could not import Real-ESRGAN modules: {e}")
    print("Make sure Real-ESRGAN is installed: pip install realesrgan")
    sys.exit(1)


def load_model(model_name='RealESRGAN_x4plus', scale=4, device='cuda', tile_size=None, half=True, allow_data_parallel=True, gpu_id=None):
    """Load Real-ESRGAN model with smart model selection"""

    # Try to auto-select x2plus for scale=2 (faster), but fallback to x4plus if unavailable
    original_model_name = model_name
    if model_name == 'RealESRGAN_x4plus' and scale == 2:
        # Check all possible locations for x2plus model
        x2plus_paths = [
            '/opt/realesrgan_models/RealESRGAN_x2plus.pth',
            os.path.join(REALESRGAN_DIR, 'weights', 'RealESRGAN_x2plus.pth'),
            'weights/RealESRGAN_x2plus.pth'
        ]

        x2plus_found = False
        for path in x2plus_paths:
            if os.path.isfile(path):
                print(f"✓ Found RealESRGAN_x2plus at {path}")
                print(f"✓ Auto-switching to RealESRGAN_x2plus for scale=2 (faster!)")
                model_name = 'RealESRGAN_x2plus'
                x2plus_found = True
                break

        if not x2plus_found:
            # Try to download x2plus model on-the-fly
            print(f"⚠️  RealESRGAN_x2plus not found in any location, attempting to download...")
            download_success = False

            try:
                os.makedirs('/opt/realesrgan_models', exist_ok=True)
                download_url = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth'
                download_path = '/opt/realesrgan_models/RealESRGAN_x2plus.pth'

                print(f"📥 Downloading from {download_url} (33 MB, may take 30-60s)...")
                import urllib.request

                # Download with progress (simple version)
                urllib.request.urlretrieve(download_url, download_path)

                if os.path.isfile(download_path) and os.path.getsize(download_path) > 1000000:  # At least 1MB
                    file_size_mb = os.path.getsize(download_path) / 1024 / 1024
                    print(f"✓ Downloaded RealESRGAN_x2plus.pth successfully! ({file_size_mb:.1f} MB)")
                    print(f"✓ Auto-switching to RealESRGAN_x2plus for scale=2 (faster!)")
                    model_name = 'RealESRGAN_x2plus'
                    download_success = True
                else:
                    print(f"❌ Download failed or file is corrupt")
            except Exception as e:
                print(f"❌ Download error: {e}")

            if not download_success:
                print(f"⚠️  Using RealESRGAN_x4plus for scale=2 (SLOW - will take 40+ minutes)")
                print(f"💡 Tip: Rebuild Docker image with x2plus model for 25-50x speedup!")
            # Keep using x4plus, will adjust outscale later

    model_path = os.path.join('/opt/realesrgan_models', f'{model_name}.pth')

    # Fallback to other locations
    if not os.path.isfile(model_path):
        model_path = os.path.join(REALESRGAN_DIR, 'weights', f'{model_name}.pth')
    if not os.path.isfile(model_path):
        model_path = f'weights/{model_name}.pth'

    if not os.path.isfile(model_path):
        print(f"ERROR: Model file not found at {model_path}")
        print(f"Searched locations:")
        print(f"  - /opt/realesrgan_models/{model_name}.pth")
        print(f"  - {REALESRGAN_DIR}/weights/{model_name}.pth")
        print(f"  - weights/{model_name}.pth")

        # Try to use URL for auto-download (only works for official models)
        if model_name in ['RealESRGAN_x4plus', 'RealESRNet_x4plus', 'RealESRGAN_x4plus_anime_6B']:
            print(f"Will attempt to auto-download from GitHub...")
            model_path = f'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/{model_name}.pth'
        else:
            print(f"ERROR: Cannot auto-download {model_name}, please provide model file")
            return None

    # Define model architecture
    if model_name == 'RealESRGAN_x4plus':
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
        netscale = 4
    elif model_name == 'RealESRNet_x4plus':
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
        netscale = 4
    elif model_name == 'RealESRGAN_x4plus_anime_6B':
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=6, num_grow_ch=32, scale=4)
        netscale = 4
    elif model_name == 'RealESRGAN_x2plus':
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=2)
        netscale = 2
    elif model_name == 'realesr-animevideov3':
        model = SRVGGNetCompact(num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=16, upscale=4, act_type='prelu')
        netscale = 4
    elif model_name == 'realesr-general-x4v3':
        model = SRVGGNetCompact(num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32, upscale=4, act_type='prelu')
        netscale = 4
    else:
        raise ValueError(f"Unknown model: {model_name}")

    # Smart tile size selection for optimal performance
    # IMPORTANT: tile=512 is FASTER than tile=0 for Real-ESRGAN due to memory access patterns!
    if tile_size is None:
        if netscale == 4 and scale == 2:
            # Using x4plus for 2x scale (inefficient) - use smaller tiles
            tile_size = 400
            print(f"⚡ Using tile_size={tile_size} (x4plus model with 2x scale)")
        elif netscale == 2:
            # x2plus model - use optimal tile size for 1080p
            # Counter-intuitive: tile=512 is FASTER than tile=0 for Real-ESRGAN!
            # Reason: Better GPU cache utilization and memory access patterns
            tile_size = 512
            print(f"⚡ Using tile_size={tile_size} (optimal for x2plus + 1080p → 4K)")
        else:
            # 4x upscaling - use tiling to avoid OOM
            tile_size = 400
            print(f"Using tile_size={tile_size}")

    print(f"🔧 GPU optimization: half=True (FP16), tile={tile_size}, tile_pad=10")

    upsampler = RealESRGANer(
        scale=netscale,
        model_path=model_path,
        model=model,
        tile=tile_size,
        tile_pad=10,
        pre_pad=0,
        half=half,  # Use FP16 if requested
        device=device,
        gpu_id=(0 if gpu_id is None else gpu_id),  # Explicitly set GPU (allow worker override)
        dni_weight=None,  # Disable DNI for speed (if available in this version)
    )

    # --- Multi-GPU support: optionally wrap model in DataParallel ---
    try:
        import torch
        if torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
        else:
            gpu_count = 0
    except Exception:
        gpu_count = 0

    # Wrap in DataParallel only when allowed (single-process mode). In multi-process per-GPU mode
    # each process should load the model on its assigned GPU and NOT wrap across all devices.
    if allow_data_parallel and gpu_count > 1:
        try:
            import torch.nn as nn
            device_ids = list(range(gpu_count))
            print(f"⚡ Multiple GPUs detected: {gpu_count} GPUs — enabling DataParallel on devices {device_ids}")
            # Wrap the underlying model with DataParallel so forward calls scatter/collect across GPUs
            try:
                upsampler.model = nn.DataParallel(upsampler.model, device_ids=device_ids)
                upsampler.multi_gpu = True
                upsampler.device_ids = device_ids
            except Exception as _e:
                print(f"Warning: DataParallel wrapping failed: {_e}")
                upsampler.multi_gpu = False
        except Exception as _e:
            print(f"Warning: failed to configure multi-gpu support: {_e}")
            upsampler.multi_gpu = False
    else:
        upsampler.multi_gpu = False

    # CRITICAL: Force model to GPU (RealESRGANer sometimes doesn't do this properly)
    if device == 'cuda':
        print(f"🔧 Forcing model to GPU...")
        try:
            # Check if CUDA is actually available
            if not torch.cuda.is_available():
                print(f"❌ ERROR: torch.cuda.is_available() = False!")
                print(f"   GPU will NOT be used! This is very slow.")
                print(f"   Check NVIDIA drivers and PyTorch CUDA installation.")
            else:
                cuda_device = torch.cuda.current_device()
                cuda_name = torch.cuda.get_device_name(cuda_device)
                print(f"✓ CUDA available: {cuda_name} (device {cuda_device})")

                # Force model to GPU
                if hasattr(upsampler, 'model'):
                    upsampler.model = upsampler.model.to(device)
                    print(f"✓ Model moved to GPU")

                # CRITICAL: Also move any sub-modules to GPU explicitly
                if hasattr(upsampler.model, 'conv_first'):
                    upsampler.model.conv_first = upsampler.model.conv_first.to(device)
                if hasattr(upsampler.model, 'conv_body'):
                    upsampler.model.conv_body = upsampler.model.conv_body.to(device)
                if hasattr(upsampler.model, 'conv_last'):
                    upsampler.model.conv_last = upsampler.model.conv_last.to(device)

                # New: move any torch.nn.Module attributes on upsampler to GPU
                try:
                    import torch.nn as nn
                    moved = 0
                    total_param_bytes = 0
                    for name, val in list(vars(upsampler).items()):
                        if isinstance(val, nn.Module):
                            try:
                                setattr(upsampler, name, val.to(device))
                                moved += 1
                            except Exception:
                                pass
                    # Compute total parameter bytes located on GPU
                    for p in upsampler.model.parameters():
                        if p.is_cuda:
                            total_param_bytes += p.numel() * p.element_size()
                    total_mb = total_param_bytes / 1024.0 / 1024.0
                    print(f"   Moved {moved} sub-modules to GPU; total params on GPU: {total_mb:.1f} MB")
                except Exception as e:
                    print(f"   Warning: failed to move submodules or compute param size: {e}")

                # Set model to eval mode and enable half precision if requested
                upsampler.model.eval()
                if upsampler.half:
                    upsampler.model = upsampler.model.half()
                    print(f"✓ Model converted to FP16 (half precision)")

                # Verify model is on GPU
                if hasattr(upsampler.model, 'parameters'):
                    first_param_device = next(upsampler.model.parameters()).device
                    print(f"✓ Model device: {first_param_device}")
                    if 'cuda' not in str(first_param_device):
                        print(f"❌ WARNING: Model is NOT on GPU! Device: {first_param_device}")

                # Additional diagnostics: param count and small forward test to ensure GPU compute
                try:
                    param_count = sum(p.numel() for p in upsampler.model.parameters())
                    print(f"   Model parameters: {param_count:,}")
                except Exception:
                    pass

                try:
                    # Small dummy forward to validate GPU execution and measure time
                    import time as _time
                    dummy_h, dummy_w = 64, 64
                    dtype = torch.half if getattr(upsampler, 'half', False) else torch.float
                    # Create dummy on primary CUDA device (DataParallel will scatter to others)
                    dummy = torch.randn(1, 3, dummy_h, dummy_w, dtype=dtype, device='cuda')
                    with torch.no_grad():
                        t0 = _time.time()
                        out_dummy = upsampler.model(dummy)
                        torch.cuda.synchronize()
                        dt = _time.time() - t0
                    print(f"   Dummy forward OK: {dt:.3f}s | GPU mem after dummy: {torch.cuda.memory_allocated()/1024**2:.1f} MB")
                except Exception as e:
                    print(f"   Dummy forward FAILED: {e}")
        except Exception as e:
            print(f"❌ Error checking/moving model to GPU: {e}")

    # Store target scale for outscale parameter (in case netscale != desired scale)
    upsampler.target_scale = scale

    return upsampler


def _tensor_from_img(img, device, half=False):
    # img: HxWxC BGR uint8
    arr = img[:, :, ::-1].astype('float32') / 255.0  # BGR->RGB
    tensor = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(device)
    if half:
        tensor = tensor.half()
    return tensor


def _img_from_tensor(tensor):
    # tensor: 1xCxHxW on CPU float (0..1)
    arr = tensor.squeeze(0).cpu().float().clamp(0, 1).numpy()
    img = (arr.transpose(1, 2, 0) * 255.0).round().astype('uint8')
    # Convert RGB->BGR for cv2
    img = img[:, :, ::-1]
    return img


def batch_upscale(upsampler, input_frames, output_dir, batch_size=4, progress_callback=None, save_workers=4, use_local_temp=False):
    """
    Batch upscale frames with optimized GPU processing

    Adds detailed per-batch timing diagnostics and writes to LOG_PATH.
    """
    total_frames = len(input_frames)
    successful = 0
    processed_frames = 0  # frames that have been processed (scheduled for save)
    start_time = time.time()
    last_log_time = start_time

    # diagnostics counters
    total_read_time = 0.0
    total_preproc_time = 0.0
    total_model_time = 0.0
    total_postproc_time = 0.0
    total_save_time = 0.0

    output_dir = Path(output_dir)
    # Optionally write to a local tmp dir first to avoid slow network writes
    local_temp_dir = None
    if use_local_temp:
        temp_name = f"realesrgan_out_{uuid.uuid4().hex[:8]}"
        local_temp_dir = Path('/tmp') / temp_name
        local_temp_dir.mkdir(parents=True, exist_ok=True)
        target_dir = local_temp_dir
        _append_log(f'Using local temp dir for writes: {local_temp_dir}')
    else:
        target_dir = output_dir

    target_dir.mkdir(parents=True, exist_ok=True)

    _append_log(f'\n=== BATCH UPSCALE START {time.strftime("%Y-%m-%d %H:%M:%S") } ===')
    _append_log(f'Frames: {total_frames}, batch_size: {batch_size}, device: {upsampler.device}, tile: {getattr(upsampler, "tile", None)}, half: {getattr(upsampler, "half", None)}')

    print(f"Starting batch upscaling: {total_frames} frames, batch_size={batch_size}")
    print(f"Using device: {upsampler.device}")

    # Quick benchmark and GPU check on first frame
    print(f"\n🔬 Processing first frame to verify GPU usage...")
    import time as time_module
    bench_start = time_module.time()

    first_frame_processed = False

    # Prepare save executor for double-buffered saving
    save_executor = concurrent.futures.ThreadPoolExecutor(max_workers=save_workers)
    outstanding_futures = []  # list of futures for scheduled saves
    max_outstanding_batches = max(4, save_workers * 4)

    for i in range(0, total_frames, batch_size):
        batch_start_time = time.time()
        batch_end = min(i + batch_size, total_frames)
        batch_frames = input_frames[i:batch_end]

        try:
            # Read batch
            t0 = time.time()
            imgs = []
            valid_paths = []
            for frame_path in batch_frames:
                img = cv2.imread(str(frame_path), cv2.IMREAD_UNCHANGED)
                if img is None:
                    print(f"ERROR: Failed to load {frame_path}")
                    _append_log(f"ERROR: Failed to load {frame_path}")
                    continue
                imgs.append(img)
                valid_paths.append(frame_path)
            t1 = time.time()
            read_time = t1 - t0
            total_read_time += read_time

            if len(imgs) == 0:
                continue

            outscale = getattr(upsampler, 'target_scale', upsampler.scale)

            # Preprocess (tensor creation)
            t0 = time.time()
            tensors = None
            if getattr(upsampler, 'device', None) == 'cuda' and torch.cuda.is_available():
                try:
                    tensors = [ _tensor_from_img(im, device='cuda', half=getattr(upsampler, 'half', False)) for im in imgs ]
                    batch_tensor = torch.cat(tensors, dim=0)
                except Exception as e:
                    # fallback
                    tensors = None
                    batch_tensor = None
                    _append_log(f'Preproc failed: {e}')
            else:
                batch_tensor = None
            t1 = time.time()
            preproc_time = t1 - t0
            total_preproc_time += preproc_time

            # Model forward
            model_time = 0.0
            outputs = []
            did_batch_forward = False
            if batch_tensor is not None:
                try:
                    t0 = time.time()
                    # suppress verbose prints from model/enhance implementations (tile progress etc.)
                    with _suppress_prints():
                        with torch.no_grad():
                            out_batch = upsampler.model(batch_tensor)
                            if getattr(upsampler, 'device', None) == 'cuda':
                                torch.cuda.synchronize()

                    t1 = time.time()
                    model_time = t1 - t0
                    total_model_time += model_time
                    # convert outputs
                    for k in range(out_batch.size(0)):
                        outputs.append(_img_from_tensor(out_batch[k:k+1]))
                    did_batch_forward = True
                except Exception as e:
                    _append_log(f'Batched forward failed: {e}')
                    # fallback per-image below

            if not did_batch_forward:
                # fallback: per-image upsampler.enhance
                t0 = time.time()
                for img in imgs:
                    try:
                        # suppress verbose enhance() printing (tiles)
                        with _suppress_prints():
                            out_img, _ = upsampler.enhance(img, outscale=outscale)

                        outputs.append(out_img)
                    except Exception as e:
                        _append_log(f'Frame enhance() failed: {e}')
                        outputs.append(None)
                t1 = time.time()
                model_time = t1 - t0
                total_model_time += model_time

            # Postproc + parallel save (ThreadPoolExecutor)
            t0 = time.time()
            futures = []
            def _save_task(out_path, out_img, src_path=None):
                try:
                    if out_img is None:
                        shutil.copy2(src_path, out_path)
                    else:
                        # ensure parent exists
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        cv2.imwrite(str(out_path), out_img)
                    return True
                except Exception as e:
                    _append_log(f'ERROR saving {out_path}: {e}')
                    return False

            # Schedule saves asynchronously (do not block main loop unless outstanding queue grows)
            for pth, out_img in zip(valid_paths, outputs):
                try:
                    frame_name = Path(pth).name
                    out_path = target_dir / frame_name
                    if out_img is None:
                        fut = save_executor.submit(_save_task, out_path, None, str(pth))
                    else:
                        fut = save_executor.submit(_save_task, out_path, out_img, None)
                    outstanding_futures.append(fut)
                except Exception as e:
                    _append_log(f'ERROR preparing save for {pth}: {e}')

            # Update processed frames counter (we scheduled these frames)
            processed_frames = batch_end

            # If too many outstanding save futures, wait for at least one batch to complete
            if len(outstanding_futures) >= max_outstanding_batches:
                done, not_done = concurrent.futures.wait(outstanding_futures, return_when=concurrent.futures.FIRST_COMPLETED)
                for f in done:
                    try:
                        ok = f.result()
                        if ok:
                            successful += 1
                    except Exception as e:
                        _append_log(f'Save future error: {e}')
                    outstanding_futures.remove(f)

            t1 = time.time()
            save_time = t1 - t0
            total_save_time += save_time
            postproc_time = save_time
            total_postproc_time += postproc_time

            # Log per-batch timings
            batch_elapsed = time.time() - batch_start_time
            _append_log(f'BATCH {i}-{batch_end}: read={read_time:.3f}s preproc={preproc_time:.3f}s model={model_time:.3f}s postproc={postproc_time:.3f}s total={batch_elapsed:.3f}s')
            # Friendly single-line progress with timestamp
            ts = time.strftime('%H:%M:%S')
            percent = int(100 * batch_end / total_frames)
            elapsed_total = time.time() - start_time
            # Use processed_frames for ETA and total_fps (reflects progress even if saves still pending)
            fps_total = processed_frames / elapsed_total if elapsed_total > 0 else 0
            eta_sec = (total_frames - processed_frames) / fps_total if fps_total > 0 else 0
            eta = f"{int(eta_sec//60)}m{int(eta_sec%60)}s" if eta_sec>0 else "0s"
            print(f"[{ts}] Processed {batch_end}/{total_frames} ({percent}%) | batch_time={batch_elapsed:.2f}s | model={model_time:.2f}s | total_fps={fps_total:.2f} | ETA: {eta}")

            # Print GPU snapshot every 5 batches
            if (i // batch_size) % 5 == 0:
                try:
                    smi = subprocess.check_output(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used', '--format=csv,noheader,nounits'], text=True)
                    _append_log('nvidia-smi: ' + smi.strip())
                except Exception:
                    pass

            # progress callback
            current_time = time.time()
            if current_time - last_log_time >= 1.0 or batch_end >= total_frames:
                elapsed = current_time - start_time
                fps = successful / elapsed if elapsed > 0 else 0
                percent = int(100 * batch_end / total_frames)
                remaining = total_frames - batch_end
                eta_sec = remaining / fps if fps > 0 else 0
                eta_min = int(eta_sec / 60)
                eta_sec_display = int(eta_sec % 60)

                batch_time = current_time - batch_start_time
                batch_fps = len(batch_frames) / batch_time if batch_time > 0 else 0

                print(f"[Real-ESRGAN] {batch_end}/{total_frames} frames ({percent}%) | {fps:.1f} fps (batch: {batch_fps:.1f} fps) | ETA: ~{eta_min}m {eta_sec_display}s", flush=True)
                last_log_time = current_time

            if progress_callback:
                progress_callback(batch_end, total_frames)

        except Exception as e:
            print(f"ERROR: Batch {i}-{batch_end} failed: {e}")
            _append_log(f'ERROR: Batch {i}-{batch_end} failed: {e}')
            # Copy originals as fallback
            for frame_path in batch_frames:
                try:
                    frame_name = Path(frame_path).name
                    output_path = output_dir / frame_name
                    shutil.copy2(frame_path, output_path)
                except Exception:
                    pass

    # End of batches
    # Wait for remaining outstanding save futures
    if outstanding_futures:
        for f in concurrent.futures.as_completed(outstanding_futures):
            try:
                ok = f.result()
                if ok:
                    successful += 1
            except Exception as e:
                _append_log(f'Save future error during final wait: {e}')

    # Shutdown save executor and wait for threads to finish
    try:
        save_executor.shutdown(wait=True)
    except Exception:
        pass

    # If wrote to local temp dir, move results to desired output_dir (may be network)
    if use_local_temp and local_temp_dir is not None:
        _append_log(f'Moving results from {local_temp_dir} -> {output_dir}')
        output_dir.mkdir(parents=True, exist_ok=True)
        mv_start = time.time()
        for f in sorted(local_temp_dir.glob('*')):
            try:
                shutil.move(str(f), str(output_dir / f.name))
            except Exception as e:
                _append_log(f'Failed to move {f}: {e}')
        try:
            local_temp_dir.rmdir()
        except Exception:
            pass
        mv_time = time.time() - mv_start
        _append_log(f'Moved results in {mv_time:.2f}s')

    _append_log(f'=== BATCH UPSCALE END: success={successful}/{total_frames} elapsed={(time.time()-start_time):.1f}s')
    _append_log(f'SUM read={total_read_time:.3f}s preproc={total_preproc_time:.3f}s model={total_model_time:.3f}s postproc={total_postproc_time:.3f}s save={total_save_time:.3f}s')
    print('\nDone. Detailed diagnostics written to', LOG_PATH)

    return successful


def auto_tune(device='cuda'):
    """Return tuned parameters based on GPU properties: batch_size, tile_size, save_workers, use_local_temp, half

    Heuristics based on total VRAM and GPU name.
    """
    try:
        import torch
        if device != 'cuda' or not torch.cuda.is_available():
            return {
                'batch_size': 4,
                'tile_size': 0,
                'save_workers': 2,
                'use_local_temp': True,
                'half': False
            }
        dev = torch.cuda.current_device()
        prop = torch.cuda.get_device_properties(dev)
        total_gb = prop.total_memory / (1024.0**3)
        name = torch.cuda.get_device_name(dev).lower()
    except Exception:
        # Fallback conservative defaults
        return {
            'batch_size': 4,
            'tile_size': 0,
            'save_workers': 4,
            'use_local_temp': True,
            'half': True
        }

    # Defaults
    batch_size = 8
    tile_size = 0
    save_workers = 4
    use_local_temp = True
    half = True

    if total_gb >= 40:
        batch_size = 32
        tile_size = 512
        save_workers = 16
    elif total_gb >= 24:
        batch_size = 16
        tile_size = 512
        save_workers = 8
    elif total_gb >= 12:
        batch_size = 8
        tile_size = 400
        save_workers = 6
    elif total_gb >= 8:
        batch_size = 4
        tile_size = 400
        save_workers = 4
    else:
        batch_size = 2
        tile_size = 256
        save_workers = 2
        half = False

    # Slight adjustments by GPU family
    if 'a100' in name or 'a6000' in name:
        # strong GPUs
        batch_size = max(batch_size, 16)
        tile_size = max(tile_size, 512)
    if '3090' in name or '3090 ti' in name or '3080' in name:
        # NVIDIA consumer cards: keep batch moderate
        batch_size = min(batch_size, 16)
    if 'rtx' in name and 'l4' in name:
        # tiny GPUs
        batch_size = min(batch_size, 4)
        half = False

    return {
        'batch_size': int(batch_size),
        'tile_size': int(tile_size),
        'save_workers': int(save_workers),
        'use_local_temp': bool(use_local_temp),
        'half': bool(half)
    }


def _split_list(lst, n):
    """Split list into n chunks (contiguous)"""
    if n <= 1:
        return [lst]
    k, m = divmod(len(lst), n)
    chunks = []
    start = 0
    for i in range(n):
        end = start + k + (1 if i < m else 0)
        chunks.append(lst[start:end])
        start = end
    return chunks


def _worker_process(frame_paths, out_dir, model_name, scale, device_id, tile_size, half, batch_size, save_workers, use_local_temp):
    """Process target for each GPU: sets device, loads model and processes given frames."""
    try:
        import torch
        # Each worker must set its CUDA device
        if device_id is not None and torch.cuda.is_available():
            torch.cuda.set_device(device_id)
        # Ensure fresh model copy in this process
        # When running as a dedicated per-GPU worker, disable DataParallel wrapping inside load_model
        upsampler = load_model(model_name, scale, device='cuda' if (device_id is not None and torch.cuda.is_available()) else 'cpu', tile_size=tile_size, half=half, allow_data_parallel=False, gpu_id=device_id)
        if upsampler is None:
            print(f"Worker {device_id}: Failed to load model")
            return
        # Create output dir
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        print(f"Worker {device_id}: processing {len(frame_paths)} frames into {out_dir}")
        # Call batch_upscale on this subset (it expects list of paths)
        batch_upscale(upsampler, frame_paths, out_dir, batch_size=batch_size, progress_callback=None, save_workers=save_workers, use_local_temp=use_local_temp)
    except Exception as e:
        print(f"Worker {device_id} failed: {e}")


def main():
    parser = argparse.ArgumentParser(description='Batch Real-ESRGAN upscaling')
    parser.add_argument('input_dir', help='Directory containing input frames')
    parser.add_argument('output_dir', help='Directory for output frames')
    parser.add_argument('--scale', type=int, default=None, choices=[2, 4], help='Upscale factor (2x or 4x)')
    parser.add_argument('--target-height', type=int, default=None, help='Target height (e.g., 2160 for 4K, 1080 for Full HD)')
    parser.add_argument('--model', default='RealESRGAN_x4plus', help='Model name')
    parser.add_argument('--batch-size', type=int, default=4, help='Frames to process at once')
    parser.add_argument('--tile-size', type=int, default=None, help='Tile size to use (override auto selection). Use 0 for no tiling')
    parser.add_argument('--no-half', action='store_true', help='Disable FP16 (use FP32)')
    parser.add_argument('--device', default='cuda', choices=['cuda', 'cpu'], help='Device to use')
    parser.add_argument('--selftest', action='store_true', help='Run a quick GPU self-test (dummy forward) and exit')
    parser.add_argument('--use-local-temp', action='store_true', help='Use local temp directory for faster saving (may use more disk space)')
    parser.add_argument('--save-workers', type=int, default=4, help='Number of worker threads for saving frames (default: 4)')
    parser.add_argument('--no-auto', action='store_true', help='Disable auto-tuning of parameters')
    parser.add_argument('--no-multiproc', action='store_true', help='Disable multi-process per-GPU splitting (force single-process DataParallel)')

    args = parser.parse_args()

    # Check CUDA
    if args.device == 'cuda' and not torch.cuda.is_available():
        print("WARNING: CUDA not available, falling back to CPU")
        args.device = 'cpu'

    # Print GPU info
    if args.device == 'cuda':
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"✓ Using GPU: {gpu_name}")
        print(f"  GPU Memory: {gpu_mem:.1f} GB")
    else:
        print("⚠ Using CPU (will be VERY slow)")

    # Write full environment diagnostics to log (useful when running via run_with_config)
    try:
        print_env_info()
    except Exception as e:
        _append_log(f'print_env_info failed: {e}')
        print(f'print_env_info failed: {e}')

    # Auto-tune parameters based on GPU, unless overridden by user
    tuned_params = {}
    if not args.no_auto:
        tuned_params = auto_tune(args.device)

    # Resolve final parameters with precedence: CLI explicit (non-default) > tuned > parser defaults
    # Parser defaults: batch_size=4, save_workers=4, tile_size=None, use_local_temp=False
    default_batch = 4
    default_save_workers = 4

    # batch_size: if user left default and auto tuned present, use tuned
    if args.batch_size == default_batch and tuned_params:
        batch_size = tuned_params.get('batch_size', args.batch_size)
    else:
        batch_size = args.batch_size

    # tile_size: if user didn't set (None) and tuned present, use tuned
    if args.tile_size is None and tuned_params:
        tile_size = tuned_params.get('tile_size', None)
    else:
        tile_size = args.tile_size

    # save_workers
    if args.save_workers == default_save_workers and tuned_params:
        save_workers = tuned_params.get('save_workers', args.save_workers)
    else:
        save_workers = args.save_workers

    # use_local_temp: CLI flag True wins; otherwise use tuned if available
    if args.use_local_temp:
        use_local_temp = True
    else:
        use_local_temp = tuned_params.get('use_local_temp', False) if tuned_params else False

    # half precision
    if args.no_half:
        half = False
    else:
        half = tuned_params.get('half', True) if tuned_params else True

    _append_log(f'Final parameters: batch_size={batch_size}, tile_size={tile_size}, save_workers={save_workers}, use_local_temp={use_local_temp}, half={half}')
    print(f"Parameters:")
    print(f"  Batch size: {batch_size}")
    print(f"  Tile size: {tile_size}")
    print(f"  Save workers: {save_workers}")
    print(f"  Use local temp: {use_local_temp}")
    print(f"  Half precision: {half}")

    # If user asked for selftest, load model and run a larger dummy forward to measure GPU usage
    if args.selftest:
        print("\n=== SELFTEST MODE: loading model and running dummy forward ===")
        upsampler = load_model(args.model, 2 if args.scale is None else args.scale, args.device, tile_size=args.tile_size, half=not args.no_half, allow_data_parallel=True, gpu_id=0)
        if upsampler is None:
            print("ERROR: Failed to load model for selftest")
            sys.exit(2)
        print("Running dummy forward (1x3x512x512) to measure GPU usage...")
        try:
            torch.cuda.empty_cache()
            dtype = torch.half if getattr(upsampler, 'half', False) else torch.float
            dummy = torch.randn(1, 3, 512, 512, dtype=dtype, device='cuda') if args.device == 'cuda' else torch.randn(1,3,512,512,dtype=dtype)
            t0 = time.time()
            with torch.no_grad():
                out = upsampler.model(dummy)
                if args.device == 'cuda':
                    torch.cuda.synchronize()
            dt = time.time() - t0
            mem_alloc = torch.cuda.memory_allocated() / 1024**2 if args.device == 'cuda' else 0
            mem_reserved = torch.cuda.memory_reserved() / 1024**2 if args.device == 'cuda' else 0
            print(f"Dummy forward time: {dt:.3f}s | GPU mem allocated: {mem_alloc:.1f} MB | reserved: {mem_reserved:.1f} MB")
            print("SELFTEST PASSED (if GPU mem > ~200MB and forward time reasonable)")
        except Exception as e:
            print(f"SELFTEST FAILED: {e}")
        sys.exit(0)

    # Get input frames
    input_dir = Path(args.input_dir)
    frames = sorted(input_dir.glob('frame_*.png'))

    if len(frames) == 0:
        print(f"ERROR: No frames found in {input_dir}")
        sys.exit(1)

    # Detect input resolution from first frame
    first_frame = cv2.imread(str(frames[0]))
    if first_frame is None:
        print(f"ERROR: Could not read first frame: {frames[0]}")
        sys.exit(1)

    input_height, input_width = first_frame.shape[:2]
    print(f"Input resolution: {input_width}x{input_height}")

    # Calculate scale if target-height is specified
    if args.target_height is not None:
        calculated_scale = args.target_height / input_height
        if calculated_scale <= 2.0:
            scale = 2
            print(f"🎯 Target: {input_width*2}x{args.target_height} → using scale=2x")
        else:
            scale = 4
            print(f"🎯 Target: {input_width*4}x{args.target_height} → using scale=4x")
            if calculated_scale > 4.0:
                print(f"⚠️  Warning: target height {args.target_height} requires {calculated_scale:.1f}x scale, but max is 4x")
    elif args.scale is not None:
        scale = args.scale
        output_height = input_height * scale
        output_width = input_width * scale
        print(f"Output resolution will be: {output_width}x{output_height}")
    else:
        # Default: auto-select scale to reach 4K (2160p) or closest
        if input_height >= 2160:
            scale = 2  # Already 4K+, just enhance
            print(f"📊 Input is 4K+, using 2x for enhancement")
        elif input_height >= 1080:
            scale = 2  # 1080p → 2160p (4K)
            print(f"📊 Auto: 1080p → 4K (2160p) using 2x scale")
        elif input_height >= 540:
            scale = 4  # 540p → 2160p (4K)
            print(f"📊 Auto: {input_height}p → 4K (2160p) using 4x scale")
        else:
            scale = 4  # Very low res, use max scale
            print(f"📊 Auto: {input_height}p → {input_height*4}p using 4x scale")

    # Load model
    # If multiple GPUs available and multiproc not disabled, run one worker per GPU to utilize GPUs independently
    try:
        # Use top-level imported `torch` (avoid local import which makes `torch` a local variable)
        gpu_count = torch.cuda.device_count() if torch.cuda.is_available() else 0
    except Exception:
        gpu_count = 0

    if gpu_count > 1 and args.device == 'cuda' and not args.no_multiproc:
        print(f"⚡ Detected {gpu_count} CUDA devices — launching {gpu_count} worker processes (one per GPU)")
        # Split frames into contiguous chunks
        chunks = _split_list(frames, gpu_count)
        from multiprocessing import Process
        workers = []
        tmp_dirs = []
        for i, chunk in enumerate(chunks):
            out_subdir = Path(args.output_dir) / f'part_{i}'
            tmp_dirs.append(out_subdir)
            p = Process(target=_worker_process, args=(chunk, str(out_subdir), args.model, scale, i, tile_size, half, batch_size, save_workers, use_local_temp))
            p.start()
            workers.append(p)

        # Wait for workers to complete
        for p in workers:
            p.join()

        # Merge outputs (move files from part_* to final output_dir)
        print(f"Merging worker outputs into {args.output_dir}")
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        for out_subdir in tmp_dirs:
            if out_subdir.exists():
                for f in sorted(out_subdir.glob('*')):
                    try:
                        target = Path(args.output_dir) / f.name
                        if target.exists():
                            target.unlink()
                        shutil.move(str(f), str(target))
                    except Exception as e:
                        print(f"Failed to move {f}: {e}")
                try:
                    out_subdir.rmdir()
                except Exception:
                    pass

        print("Multi-process upscaling done")
        sys.exit(0)
    else:
        print(f"Loading Real-ESRGAN model ({args.model}) for {scale}x upscaling...")
        upsampler = load_model(args.model, scale, args.device, tile_size=tile_size, half=half, allow_data_parallel=True, gpu_id=0)
        print("✓ Model loaded")

    print(f"Found {len(frames)} input frames")
    print(f"Upscale factor: {scale}x")
    print(f"Batch size: {batch_size}")
    print()

    # Process
    start_time = time.time()
    last_progress = 0

    def progress_callback(current, total):
        nonlocal last_progress
        if current - last_progress >= 30 or current == total:
            elapsed = time.time() - start_time
            fps = current / elapsed if elapsed > 0 else 0
            eta_sec = (total - current) / fps if fps > 0 else 0
            eta_min = int(eta_sec / 60)
            print(f"Processed {current}/{total} frames ({fps:.1f} fps, ETA: ~{eta_min}m)")
            last_progress = current

    successful = batch_upscale(
         upsampler=upsampler,
         input_frames=frames,
         output_dir=args.output_dir,
         batch_size=batch_size,
         progress_callback=progress_callback,
         save_workers=save_workers,
         use_local_temp=use_local_temp
     )

    elapsed = time.time() - start_time
    print()
    print(f"✓ Batch upscaling complete in {elapsed:.1f}s")
    print(f"  Successful: {successful} / {len(frames)} frames")
    print(f"  Average: {len(frames)/elapsed:.1f} fps")

    if successful < len(frames) * 0.9:
        print("⚠ WARNING: Less than 90% of frames upscaled successfully")
        sys.exit(1)


if __name__ == '__main__':
    main()
