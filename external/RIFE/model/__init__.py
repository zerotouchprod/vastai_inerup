# Lightweight compatibility shim to expose a `Model` symbol under `model` package
# This helps older RIFE model files expecting `from model import ...` to work.
import importlib
import importlib.util
import os

Model = None
_tried = []

candidates = [
    'train_log.RIFE_HDv3',
    'train_log.RIFE_HD',
    'RIFE_HDv3',
    'model.RIFE',
    'train_log.refine',
]

for name in candidates:
    try:
        _tried.append(f"try_import:{name}")
        mod = importlib.import_module(name)
        if hasattr(mod, 'Model'):
            Model = getattr(mod, 'Model')
            break
    except Exception as e:
        _tried.append(f"fail_import:{name}:{type(e).__name__}")

# file-based fallback: scan train_log/ and model/ for any file defining Model
if Model is None:
    repo_root = os.path.dirname(os.path.dirname(__file__))
    for sub in ('train_log', 'model'):
        d = os.path.join(repo_root, sub)
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.lower().endswith('.py'):
                continue
            path = os.path.join(d, fname)
            try:
                spec = importlib.util.spec_from_file_location(f'rife_shim_{fname[:-3]}', path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _tried.append(f"file_ok:{path}")
                if hasattr(mod, 'Model'):
                    Model = getattr(mod, 'Model')
                    break
            except Exception as e:
                _tried.append(f"file_fail:{path}:{type(e).__name__}")
        if Model is not None:
            break

if Model is None:
    # leave Model as None — callers will receive ModuleNotFoundError or similar when trying to use it
    # but provide diagnostics if someone imports model and inspects _tried
    pass

__all__ = ['Model', '_tried']

