#!/usr/bin/env python3
"""
Local persistent runner for RIFE tailored to this project.
Accepts: --repo-dir, --input, --output, --factor
This file is intentionally named with a leading underscore to avoid conflicts
with other similarly named scripts in the environment.
"""
import os
import sys
import argparse
from importlib import import_module
from glob import glob


def log(*args, **kwargs):
    print('[persistent-local]', *args, **kwargs)


def find_callable(mod):
    candidates = ['inference_pair', 'inference', 'infer', 'process_pair', 'run_pair']
    # Accept either a module-like object or a dict namespace (returned by runpy.run_path)
    for name in candidates:
        try:
            if isinstance(mod, dict):
                fn = mod.get(name)
            else:
                fn = getattr(mod, name, None)
        except Exception:
            fn = None
        if callable(fn):
            return fn
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repo-dir', required=True)
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--factor', type=int, default=2)
    args = p.parse_args()

    repo = args.repo_dir
    input_dir = args.input
    out_dir = args.output
    factor = args.factor

    if not os.path.isdir(repo):
        log('repo missing:', repo)
        return 3
    if not os.path.isdir(input_dir):
        log('input dir missing:', input_dir)
        return 4
    os.makedirs(out_dir, exist_ok=True)

    sys.path.insert(0, repo)
    try:
        os.chdir(repo)
    except Exception:
        pass

    # Prefer module import by name if available. Many RIFE forks parse argparse at import-time,
    # so temporarily set sys.argv to a safe value to avoid SystemExit from argparse.
    try:
        # Prevent top-level argparse parsing in many RIFE forks by monkeypatching parse_args
        import argparse as _argparse
        _orig_parse_args = _argparse.ArgumentParser.parse_args
        _orig_parse_known = _argparse.ArgumentParser.parse_known_args
        def _fake_parse_args(self, *a, **k):
            ns = _argparse.Namespace()
            # Provide common RIFE CLI attributes to avoid AttributeError on import
            for _k in ('img','exp','ratio','rthreshold','rmaxcycles','model','modelDir','model_dir','MODELDIR','train_log'):
                setattr(ns, _k, None)
            return ns
        def _fake_parse_known(self, *a, **k):
            ns = _argparse.Namespace()
            for _k in ('img','exp','ratio','rthreshold','rmaxcycles','model','modelDir','model_dir','MODELDIR','train_log'):
                setattr(ns, _k, None)
            return (ns, [])

        _argparse.ArgumentParser.parse_args = _fake_parse_args
        _argparse.ArgumentParser.parse_known_args = _fake_parse_known

        old_argv = sys.argv
        sys.argv = [os.path.join(repo, 'inference_img.py')]
        try:
            mod = import_module('inference_img')
            log('Imported inference_img from', repo)
        finally:
            sys.argv = old_argv
            # restore argparse
            _argparse.ArgumentParser.parse_args = _orig_parse_args
            _argparse.ArgumentParser.parse_known_args = _orig_parse_known
    except Exception as e:
        log('importlib import failed:', e)
        # Try to create a safe modified copy of inference_img.py that prevents top-level execution
        try:
            import tempfile
            import shutil
            src = os.path.join(repo, 'inference_img.py')
            if os.path.isfile(src):
                tmpdir = tempfile.mkdtemp(prefix='rife_mod_')
                dst = os.path.join(tmpdir, 'inference_img_mod.py')
                with open(src, 'r', encoding='utf-8') as f:
                    orig = f.read()
                # Header: safe argparse monkeypatch to avoid required-args crashes during import
                header = """
import argparse as _argparse
_orig_parse_args = _argparse.ArgumentParser.parse_args
_orig_parse_known = _argparse.ArgumentParser.parse_known_args
def _safe_parse_args(self, *a, **k):
    try:
        return _orig_parse_args(self, *a, **k)
    except Exception:
        from types import SimpleNamespace as _NS
        ns = _NS()
        # common RIFE argument names: provide None defaults to avoid AttributeError
        for _k in ('img','exp','ratio','rthreshold','rmaxcycles','model','modelDir','model_dir','MODELDIR','train_log'):
            setattr(ns, _k, None)
        return ns
def _safe_parse_known(self, *a, **k):
    try:
        return _orig_parse_known(self, *a, **k)
    except Exception:
        return (_safe_parse_args(self, *a, **k), [])
_argparse.ArgumentParser.parse_args = _safe_parse_args
_argparse.ArgumentParser.parse_known_args = _safe_parse_known
"""
                # Create modified file with header + original content
                with open(dst, 'w', encoding='utf-8') as f:
                    f.write(header + '\n' + orig)
                # Import modified module via spec_from_file_location
                try:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location('inference_img_mod', dst)
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules['inference_img_mod'] = mod
                    spec.loader.exec_module(mod)
                    log('Imported modified inference_img module from', dst)
                except Exception as e2:
                    log('Failed to import modified inference_img module:', e2)
                    shutil.rmtree(tmpdir, ignore_errors=True)
                    return 2
            else:
                log('Original inference_img.py not found at', src)
                return 2
        except Exception as e3:
            log('Error while attempting to create modified inference_img copy:', e3)
            return 2

    fn = find_callable(mod)
    if fn is None:
        log('No high-level callable found in inference_img; persistent mode unsupported')
        return 2

    frames = sorted(glob(os.path.join(input_dir, '*.png')))
    if len(frames) < 2:
        log('Not enough frames in', input_dir)
        return 5

    total_pairs = len(frames) - 1
    log('Processing', total_pairs, 'pairs using', fn.__name__)

    # Build pairs list with global index (1-based) to ensure deterministic merging
    pairs = []
    for i in range(total_pairs):
        A = frames[i]
        B = frames[i+1]
        pairs.append((A, B, i+1))

    # Determine worker count: prefer CUDA devices if available
    workers_arg = os.environ.get('RIFE_PERSIST_WORKERS', '')
    use_multiproc = True
    worker_count = 1
    if workers_arg.isdigit() and int(workers_arg) > 0:
        worker_count = int(workers_arg)
    else:
        try:
            import torch
            if torch.cuda.is_available():
                device_count = torch.cuda.device_count()
            else:
                device_count = 0
        except Exception:
            device_count = 0

        if device_count > 1:
            worker_count = device_count
        else:
            worker_count = 1

    # Allow env to disable multiproc
    if os.environ.get('RIFE_PERSIST_NO_MULTIPROC', '') == '1':
        worker_count = 1

    # Bound workers by number of pairs
    worker_count = max(1, min(worker_count, total_pairs))

    # Helper to split list into nearly equal chunks
    def _split_chunks(lst, n):
        k, m = divmod(len(lst), n)
        chunks = []
        start = 0
        for i in range(n):
            end = start + k + (1 if i < m else 0)
            chunks.append(lst[start:end])
            start = end
        return chunks

    # Worker target: runs in new process, must set CUDA_VISIBLE_DEVICES before importing torch
    def _worker_target(repo_dir, chunk_pairs, out_dir, factor, device_id, worker_id):
        try:
            # Set visible device for this process before importing torch
            if device_id is not None:
                os.environ['CUDA_VISIBLE_DEVICES'] = str(device_id)
            # Ensure cwd and sys.path
            sys.path.insert(0, repo_dir)
            try:
                os.chdir(repo_dir)
            except Exception:
                pass

            # Load module or fallback to runpy
            mod_local = None
            try:
                # monkeypatch argparse to avoid parse_args SystemExit during import
                import argparse as _argparse
                _orig_parse_args = _argparse.ArgumentParser.parse_args
                _orig_parse_known = _argparse.ArgumentParser.parse_known_args
                def _fake_parse_args(self, *a, **k):
                    ns = _argparse.Namespace()
                    for _k in ('img','exp','ratio','rthreshold','rmaxcycles','model','modelDir','model_dir','MODELDIR','train_log'):
                        setattr(ns, _k, None)
                    return ns
                def _fake_parse_known(self, *a, **k):
                    ns = _argparse.Namespace()
                    for _k in ('img','exp','ratio','rthreshold','rmaxcycles','model','modelDir','model_dir','MODELDIR','train_log'):
                        setattr(ns, _k, None)
                    return (ns, [])

                _argparse.ArgumentParser.parse_args = _fake_parse_args
                _argparse.ArgumentParser.parse_known_args = _fake_parse_known

                old_argv = sys.argv
                sys.argv = [os.path.join(repo_dir, 'inference_img.py')]
                try:
                    mod_local = import_module('inference_img')
                finally:
                    sys.argv = old_argv
                    _argparse.ArgumentParser.parse_args = _orig_parse_args
                    _argparse.ArgumentParser.parse_known_args = _orig_parse_known
            except Exception as e:
                log(f'[worker {worker_id}] import failed: {e}; attempting modified copy fallback')
                # try modified copy approach
                try:
                    import tempfile, shutil, importlib.util
                    src = os.path.join(repo_dir, 'inference_img.py')
                    if os.path.isfile(src):
                        tmpdir = tempfile.mkdtemp(prefix=f'rife_mod_worker_{worker_id}_')
                        dst = os.path.join(tmpdir, 'inference_img_mod.py')
                        with open(src, 'r', encoding='utf-8') as f:
                            orig = f.read()
                        header = """
import argparse as _argparse
_orig_parse_args = _argparse.ArgumentParser.parse_args
_orig_parse_known = _argparse.ArgumentParser.parse_known_args
def _safe_parse_args(self, *a, **k):
    try:
        return _orig_parse_args(self, *a, **k)
    except Exception:
        from types import SimpleNamespace as _NS
        ns = _NS()
        for _k in ('img','exp','ratio','rthreshold','rmaxcycles','model','modelDir','model_dir','MODELDIR','train_log'):
            setattr(ns, _k, None)
        return ns
def _safe_parse_known(self, *a, **k):
    try:
        return _orig_parse_known(self, *a, **k)
    except Exception:
        return (_safe_parse_args(self, *a, **k), [])
_argparse.ArgumentParser.parse_args = _safe_parse_args
_argparse.ArgumentParser.parse_known_args = _safe_parse_known
"""
                        with open(dst, 'w', encoding='utf-8') as f:
                            f.write(header + '\n' + orig)
                        spec = importlib.util.spec_from_file_location(f'inference_img_worker_mod_{worker_id}', dst)
                        mod_local = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod_local)
                        log(f'[worker {worker_id}] imported modified module from', dst)
                    else:
                        log(f'[worker {worker_id}] original inference_img.py not found at', src)
                        return 2
                except Exception as e2:
                    log('[worker', worker_id, '] failed to load modified inference_img:', e2)
                    return 2

            fn_local = find_callable(mod_local)
            if fn_local is None:
                log('[worker', worker_id, '] no callable found in inference_img; aborting')
                return 2

            # Try to locate a batch-capable function in the module (best-effort)
            batch_candidates = ['inference_pairs', 'inference_batch', 'infer_batch', 'infer_pairs', 'batch_infer', 'run_pairs']
            batch_fn = None
            for name in batch_candidates:
                try:
                    cand = getattr(mod_local, name, None) if not isinstance(mod_local, dict) else mod_local.get(name)
                except Exception:
                    cand = None
                if callable(cand):
                    batch_fn = cand
                    log(f'[worker {worker_id}] using batch function: {name}')
                    break

            # Determine batch size from env or default
            try:
                batch_size = int(os.environ.get('RIFE_BATCH_SIZE', '4'))
            except Exception:
                batch_size = 4

            # Prepare per-worker output dir
            worker_out = os.path.join(out_dir, f'worker_{worker_id}')
            os.makedirs(worker_out, exist_ok=True)

            # Process assigned pairs sequentially, reusing loaded model
            for (A, B, idx) in chunk_pairs:
                log(f'[worker {worker_id}] pair idx={idx} {os.path.basename(A)} + {os.path.basename(B)}')
                try:
                    # snapshot outputs before
                    pre_repo = set(glob(os.path.join(repo_dir, '*.png')))
                    pre_out = set(glob(os.path.join(out_dir, '*.png')))

                    # call the function trying common signatures
                    try:
                        fn_local(A, B, worker_out, factor)
                    except TypeError:
                        try:
                            fn_local(A, B, factor, worker_out)
                        except TypeError:
                            fn_local(A, B)

                    # detect new files in repo and out_dir
                    post_repo = set(glob(os.path.join(repo_dir, '*.png')))
                    post_out = set(glob(os.path.join(out_dir, '*.png')))
                    new_files = (post_repo - pre_repo) | (post_out - pre_out)

                    if not new_files:
                        log(f'[worker {worker_id}] WARNING: no new output files for pair idx={idx}')
                        continue

                    # Move/rename new files into worker_out with deterministic per-pair prefix
                    seq = 1
                    for nf in sorted(new_files):
                        try:
                            target = os.path.join(worker_out, f'pair_{idx:06d}_{seq:03d}.png')
                            os.replace(nf, target)
                            log(f'[worker {worker_id}] saved {os.path.basename(target)}')
                        except Exception:
                            try:
                                # fallback copy
                                import shutil
                                target = os.path.join(worker_out, f'pair_{idx:06d}_{seq:03d}.png')
                                shutil.copy2(nf, target)
                                log(f'[worker {worker_id}] copied {os.path.basename(target)}')
                            except Exception as e:
                                log(f'[worker {worker_id}] failed to move/copy {nf}:', e)
                        seq += 1

                except Exception as e:
                    log(f'[worker {worker_id}] error processing pair idx={idx}:', e)
                    return 1

            log(f'[worker {worker_id}] done')
            return 0
        except Exception as e:
            log(f'[worker {worker_id}] unexpected failure:', e)
            return 2

    # If only one worker, run in-process for simpler behavior
    if worker_count <= 1:
        # Single-process behavior: reuse existing fn and loop sequentially
        for (A, B, idx) in pairs:
            log('pair', os.path.basename(A), os.path.basename(B))
            try:
                try:
                    fn(A, B, out_dir, factor)
                except TypeError:
                    try:
                        fn(A, B, factor, out_dir)
                    except TypeError:
                        fn(A, B)
            except SystemExit as se:
                log('callable exited with', se.code)
                return 1
            except Exception as e:
                log('error calling callable:', e)
                return 1

        log('Done processing pairs (single-process)')
        return 0

    # Multi-process: split pairs and spawn worker processes (spawn start method)
    log(f'Using multi-process persistent runner with {worker_count} workers')
    chunks = _split_chunks(pairs, worker_count)
    from multiprocessing import get_context
    ctx = get_context('spawn')
    procs = []
    for wid, chunk in enumerate(chunks):
        device_id = wid  # map worker index to GPU id (0..)
        p = ctx.Process(target=_worker_target, args=(repo, chunk, out_dir, factor, device_id, wid))
        p.start()
        procs.append((p, wid))

    # wait for workers
    exit_codes = []
    for p, wid in procs:
        p.join()
        exit_codes.append(p.exitcode)
        log(f'worker {wid} exitcode={p.exitcode}')

    # Merge per-worker outputs into sequential assembled dir
    assembled = os.path.join(out_dir, 'assembled')
    os.makedirs(assembled, exist_ok=True)
    out_index = 1
    for idx in range(1, total_pairs+1):
        # collect files for this pair from all worker dirs
        found = []
        for wid in range(worker_count):
            worker_out = os.path.join(out_dir, f'worker_{wid}')
            pattern = os.path.join(worker_out, f'pair_{idx:06d}_*.png')
            for fpath in sorted(glob(pattern)):
                found.append(fpath)
        # copy/move found files to assembled sequential names
        for f in found:
            target = os.path.join(assembled, f'frame_{out_index:06d}.png')
            try:
                os.replace(f, target)
            except Exception:
                import shutil
                shutil.copy2(f, target)
            out_index += 1

    log('Multi-process persistent runner finished, assembled frames at', assembled)
    return 0


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
