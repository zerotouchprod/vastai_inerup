"""GPU-specific Real-ESRGAN performance profiles (measured tile/batch per GPU, model, resolution).

Profiles live in perf_profiles.yaml next to this module (shipped in the image),
or in REAL_ESRGAN_PROFILES_FILE. REAL_ESRGAN_PROFILES=off disables them.
Selection is an exact match on (normalized GPU, model, scale, input WxH, fp16);
there is no nearest-neighbour or orientation guessing.
"""

import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

DEFAULT_PROFILES_FILE = Path(__file__).with_name("perf_profiles.yaml")

_CACHE = {}


@dataclass(frozen=True)
class PerfProfile:
    id: str
    gpu: str
    model: str
    scale: int
    input_width: int
    input_height: int
    half: bool
    tile: int
    gpu_batch: int
    reference_fps: Optional[float] = None

    def summary(self) -> dict:
        return asdict(self)


def normalize_gpu_name(name) -> str:
    """'NVIDIA GeForce RTX 4080' / 'RTX 4080' / 'rtx_4080' -> 'RTX 4080'."""
    s = str(name or "").upper().replace("_", " ")
    s = re.sub(r"\b(NVIDIA|GEFORCE|CORPORATION)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_input(value):
    m = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", str(value))
    if not m:
        raise ValueError(f"profile input must be WIDTHxHEIGHT, got {value!r}")
    return int(m.group(1)), int(m.group(2))


def parse_profiles(data) -> List[PerfProfile]:
    out = []
    seen = set()
    for raw in (data or {}).get("profiles") or []:
        w, h = _parse_input(raw["input"])
        tile = int(raw.get("tile", 0))
        batch = int(raw.get("gpu_batch", 1))
        if tile < 0 or batch < 1:
            raise ValueError(
                f"profile {raw.get('id')}: tile>=0 and gpu_batch>=1 required"
            )
        p = PerfProfile(
            id=str(raw["id"]),
            gpu=normalize_gpu_name(raw["gpu"]),
            model=str(raw["model"]),
            scale=int(raw["scale"]),
            input_width=w,
            input_height=h,
            half=bool(raw.get("half", True)),
            tile=tile,
            gpu_batch=batch,
            reference_fps=(
                float(raw["reference_fps"])
                if raw.get("reference_fps") is not None
                else None
            ),
        )
        key = (p.gpu, p.model, p.scale, p.input_width, p.input_height, p.half)
        if key in seen:
            raise ValueError(f"duplicate profile key {key}")
        seen.add(key)
        out.append(p)
    return out


def profiles_enabled() -> bool:
    return os.getenv("REAL_ESRGAN_PROFILES", "on").strip().lower() not in (
        "0",
        "off",
        "false",
        "no",
    )


def profiles_path() -> Path:
    env = os.getenv("REAL_ESRGAN_PROFILES_FILE")
    return Path(env) if env else DEFAULT_PROFILES_FILE


def load_profiles(path=None) -> List[PerfProfile]:
    """Parsed profiles (cached per path+mtime). A broken file raises: fix it, don't guess."""
    path = Path(path) if path else profiles_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    cached = _CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    import yaml

    with open(path, encoding="utf-8") as fh:
        profiles = parse_profiles(yaml.safe_load(fh))
    _CACHE[str(path)] = (mtime, profiles)
    return profiles


def select_profile(
    gpu_name, model_name, scale, input_width, input_height, half=True, profiles=None
) -> Optional[PerfProfile]:
    if profiles is None:
        if not profiles_enabled():
            return None
        profiles = load_profiles()
    gpu = normalize_gpu_name(gpu_name)
    for p in profiles:
        if (
            p.gpu == gpu
            and p.model == str(model_name)
            and p.scale == int(scale)
            and p.input_width == int(input_width)
            and p.input_height == int(input_height)
            and p.half == bool(half)
        ):
            return p
    return None
