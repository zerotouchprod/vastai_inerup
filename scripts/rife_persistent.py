#!/usr/bin/env python3
"""
Persistent/batch runner for RIFE (best-effort).
This script tries to import the repository's `inference_img` module and use
its in-process API (if any) to process many frame pairs without reloading the
model for each pair. If the module does not expose a callable API, the script
exits with code 2 to allow fallback.

Usage:
  python3 scripts/rife_persistent.py --repo-dir /workspace/project/external/RIFE \
      --input /tmp/rife_tmp.xxx/input --output /tmp/rife_tmp.xxx/output --factor 2

The script will process consecutive pairs (frame_000001.png + frame_000002.png, ...)
and write outputs into the specified output directory. It logs to stdout/stderr
which is captured by the caller.

This is a best-effort helper; various forks of RIFE expose different APIs. The
script tries several common function names inside `inference_img`:
  - inference_pair(imgA, imgB, out_dir, factor)
  - inference(imgA, imgB, out_dir, factor)
  - infer(imgA, imgB, out_dir, factor)
If none are found the script fails and returns 2 so the caller can fallback to
per-pair subprocess invocation.
"""
import os
import sys
import argparse
import importlib
from glob import glob


def log(*args, **kwargs):
    print("[persistent]", *args, **kwargs)


def find_callable(mod):
    candidates = [
        'inference_pair',
        'inference',
        'infer',
        'process_pair',
        'run_pair',
    ]
    for name in candidates:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    # Some scripts provide a main that accepts parsed args; we avoid using main since it often parses CLI
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

    # Basic checks
    if not os.path.isdir(repo):
        log('repo dir missing:', repo)
        return 3
    if not os.path.isdir(input_dir):
        log('input dir missing:', input_dir)
        return 4
    os.makedirs(out_dir, exist_ok=True)

    # Put repo on path and chdir so imports and relative file access work
    sys.path.insert(0, repo)
    try:
        os.chdir(repo)
    except Exception:
        pass

    try:
        mod = importlib.import_module('inference_img')
        log('Imported inference_img module from', repo)
    except Exception as e:
        log('Failed to import inference_img:', e)
        return 2

    fn = find_callable(mod)
    if fn is None:
        log('No high-level callable found in inference_img; persistent mode not supported for this fork')
        return 2

    # collect frames
    frames = sorted(glob(os.path.join(input_dir, '*.png')))
    if len(frames) < 2:
        log('Not enough frames in', input_dir)
        return 5

    log('Processing', len(frames)-1, 'pairs using', fn.__name__)

    # Attempt to call function for each pair
    count = 0
    for i in range(len(frames)-1):
        A = frames[i]
        B = frames[i+1]
        log(f'Calling {fn.__name__} for', os.path.basename(A), os.path.basename(B))
        try:
            # Try common signatures
            try:
                res = fn(A, B, out_dir, factor)
            except TypeError:
                # try alternative: (imgA, imgB, factor, out_dir)
                try:
                    res = fn(A, B, factor, out_dir)
                except TypeError:
                    # try simple two-arg function that returns outputs
                    res = fn(A, B)
            # If function returns False/None treat as success unless raises
        except SystemExit as se:
            log('Callable invoked sys.exit; aborting with', se.code)
            return 1
        except Exception as e:
            log('Error while calling function for pair', A, B, '-', e)
            return 1
        count += 1

    log('Processed', count, 'pairs successfully')
    return 0


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)

