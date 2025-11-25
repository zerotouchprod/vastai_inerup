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
import importlib
from glob import glob


def log(*args, **kwargs):
    print('[persistent-local]', *args, **kwargs)


def find_callable(mod):
    candidates = ['inference_pair', 'inference', 'infer', 'process_pair', 'run_pair']
    for name in candidates:
        fn = getattr(mod, name, None)
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

    # Prefer module import by name if available
    try:
        mod = importlib.import_module('inference_img')
        log('Imported inference_img from', repo)
    except Exception as e:
        # As fallback, try runpy to execute script (but we prefer import to find callables)
        log('Failed to import inference_img:', e)
        return 2

    fn = find_callable(mod)
    if fn is None:
        log('No high-level callable found in inference_img; persistent mode unsupported')
        return 2

    frames = sorted(glob(os.path.join(input_dir, '*.png')))
    if len(frames) < 2:
        log('Not enough frames in', input_dir)
        return 5

    log('Processing', len(frames)-1, 'pairs using', fn.__name__)
    for i in range(len(frames)-1):
        A = frames[i]
        B = frames[i+1]
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

    log('Done processing pairs')
    return 0


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)

