#!/usr/bin/env python3
"""
vast_submit.py

Lightweight helper to automate creating a vast.ai instance via the public HTTP API.

Purpose:
- Find an affordable offer matching requested constraints (min VRAM, max price).
- Create an instance that runs a specified Docker image and command.
- Wait for instance to become running and print its info.
- Optionally poll instance until it's terminated and print final info.

Design notes / constraints:
- This script assumes you have a reachable input URL (HTTP/HTTPS) that the remote instance can wget/curl.
  If your input is a local file, upload it to a temporary public location (S3, presigned URL, or similar)
  before using the `--input-url` mode.
- Authentication: set VAST_API_KEY in environment.
- This script is intentionally conservative: it does not try to SCP local files, nor modify billing behaviour.

Usage examples:
  # simple search + create instance that will download input and run pipeline
  export VAST_API_KEY=your_key_here
  python vast_submit.py \
    --image myrepo/myimage:latest \
    --cmd "/workspace/run_ncnn.sh /workspace/input.mp4 /workspace/output" \
    --input-url "https://example.com/input.mp4" \
    --min-vram 4 --max-price 0.25

Requirements: Python 3.8+, requests
Install deps: pip install requests

Note: This script uses the public (community) Vast API endpoints as JSON; adapt endpoints/fields if your organisation
uses a different API surface or a newer version.

"""

import os
import sys
import time
import argparse
import yaml
from typing import Any, Dict, List, Optional
from pathlib import Path

# Load .env from repo root if present. Prefer python-dotenv (dynamically imported), else fallback to a minimal parser.
_env_path = Path(__file__).resolve().parent / '.env'
if _env_path.exists():
    try:
        import importlib
        _dotenv = importlib.import_module('dotenv')
        load_dotenv = getattr(_dotenv, 'load_dotenv')
        # load_dotenv will not overwrite existing env vars by default
        load_dotenv(dotenv_path=str(_env_path))
    except Exception:
        # fallback parser: don't overwrite existing env vars
        try:
            with open(_env_path, 'r', encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if not _line or _line.startswith('#') or _line.startswith('//'):
                        continue
                    if '=' not in _line:
                        continue
                    _k, _v = _line.split('=', 1)
                    _k = _k.strip()
                    _v = _v.strip().strip('"').strip("'")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
        except Exception:
            print('Warning: failed to parse .env file; skipping')

try:
    import requests
except Exception:
    print("Missing dependency: requests. Install with `pip install requests`.")
    raise
from requests.exceptions import RequestException

API_BASE = os.environ.get("VAST_API_BASE", "https://api.vast.ai/v0")
API_KEY = os.environ.get("VAST_API_KEY")

if not API_KEY:
    print("Error: VAST_API_KEY environment variable is not set. Export it and retry.")
    sys.exit(2)

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# Load host blacklist from config.yaml (optional). This allows setting e.g.:
# vast:
#   host_blacklist: [155386]
VAST_HOST_BLACKLIST = []
try:
    cfg_path = Path(__file__).resolve().parent / 'config.yaml'
    if cfg_path.exists():
        try:
            with open(cfg_path, 'r', encoding='utf-8') as _cf:
                _cfg = yaml.safe_load(_cf) or {}
                _hb = None
                if isinstance(_cfg, dict):
                    # nested under `vast.host_blacklist` is preferred
                    if 'vast' in _cfg and isinstance(_cfg['vast'], dict):
                        _hb = _cfg['vast'].get('host_blacklist')
                    # legacy/top-level keys
                    if _hb is None:
                        _hb = _cfg.get('vast_host_blacklist') or _cfg.get('host_blacklist')
                if isinstance(_hb, list):
                    # coerce to ints and filter invalid values
                    VAST_HOST_BLACKLIST = [int(x) for x in _hb if x is not None]
                    if VAST_HOST_BLACKLIST:
                        print(f"Info: loaded host blacklist from config.yaml: {VAST_HOST_BLACKLIST}")
        except Exception as _e:
            print(f"Warning: failed to parse config.yaml for host_blacklist: {_e}")
except Exception:
    # non-fatal
    pass


def api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Try the configured API_BASE first, then optionally an alternate console endpoint
    attempted = []
    # Candidate bases: current API_BASE, then a known alternate (console.vast.ai)
    alt = os.environ.get("VAST_API_FALLBACK", "https://console.vast.ai/api/v0")
    bases = [API_BASE]
    if alt and alt.rstrip('/') not in [b.rstrip('/') for b in bases]:
        bases.append(alt)

    last_exc: Optional[RequestException] = None
    for base in bases:
        attempted.append(base)
        url = f"{base.rstrip('/')}{path}"
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            r.raise_for_status()
            # If we succeeded on a fallback base, update global API_BASE for subsequent calls
            if base != API_BASE:
                try:
                    # update module-level API_BASE so future calls reuse working endpoint
                    globals()['API_BASE'] = base
                    print(f"Info: switched Vast API base to {base} (fallback succeeded).")
                except Exception:
                    pass
            return r.json()
        except RequestException as e:
            last_exc = e
            # try next base
            continue

    # All attempts failed — prepare an actionable message
    msg = (
        f"Failed to contact Vast.ai API. Attempted endpoints: {', '.join(attempted)}.\n"
        f"Last error: {last_exc}\n"
        "This may be caused by network/DNS issues, a proxy blocking requests, or temporary outage.\n"
        "Suggestions:\n"
        "  - Check your network / DNS resolution (e.g. 'ping api.vast.ai' or 'nslookup api.vast.ai').\n"
        "  - If you're behind a proxy, set HTTP(S)_PROXY env vars or configure requests accordingly.\n"
        "  - If you want to skip market search and directly create an instance, use --offline --offer-id <OFFER_ID>.\n"
        "  - You can override the endpoint explicitly with VAST_API_BASE or VAST_API_FALLBACK env vars.\n"
    )
    raise RuntimeError(msg) from last_exc


def api_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Mirror the same fallback behavior used in api_get
    attempted = []
    alt = os.environ.get("VAST_API_FALLBACK", "https://console.vast.ai/api/v0")
    bases = [API_BASE]
    if alt and alt.rstrip('/') not in [b.rstrip('/') for b in bases]:
        bases.append(alt)

    last_exc: Optional[RequestException] = None
    for base in bases:
        attempted.append(base)
        url = f"{base.rstrip('/')}{path}"
        try:
            r = requests.post(url, headers=HEADERS, json=payload, timeout=60)
            r.raise_for_status()
            if base != API_BASE:
                try:
                    globals()['API_BASE'] = base
                    print(f"Info: switched Vast API base to {base} (fallback succeeded).")
                except Exception:
                    pass
            return r.json()
        except RequestException as e:
            last_exc = e
            continue

    msg = (
        f"Failed to contact Vast.ai API. Attempted endpoints: {', '.join(attempted)}.\n"
        f"Last error: {last_exc}\n"
        "See suggestions in api_get message.\n"
    )
    raise RuntimeError(msg) from last_exc


def api_put(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    # PUT with same fallback behavior as api_post
    attempted = []
    alt = os.environ.get("VAST_API_FALLBACK", "https://console.vast.ai/api/v0")
    bases = [API_BASE]
    if alt and alt.rstrip('/') not in [b.rstrip('/') for b in bases]:
        bases.append(alt)

    last_exc: Optional[RequestException] = None
    for base in bases:
        attempted.append(base)
        url = f"{base.rstrip('/')}{path}"
        try:
            r = requests.put(url, headers=HEADERS, json=payload, timeout=60)
            r.raise_for_status()
            if base != API_BASE:
                try:
                    globals()['API_BASE'] = base
                    print(f"Info: switched Vast API base to {base} (fallback succeeded).")
                except Exception:
                    pass
            return r.json()
        except RequestException as e:
            last_exc = e
            continue

    msg = (
        f"Failed to contact Vast.ai API. Attempted endpoints: {', '.join(attempted)}.\n"
        f"Last error: {last_exc}\n"
        "See suggestions in api_get message.\n"
    )
    raise RuntimeError(msg) from last_exc


def search_offers(min_vram: int = 4, max_price: float = 1.0, limit: int = 20,
                  min_price: float = None, min_reliability: float = None,
                  gpu_models: List[str] = None, min_cuda: float = None,
                  min_dlperf: float = None, min_dlperf_per_dphtotal: float = None,
                  min_inet_down: float = None, min_inet_up: float = None,
                  min_cpu_cores: int = None, min_cpu_ram: int = None,
                  min_disk_bw: float = None, min_gpu_mem_bw: float = None,
                  datacenter: bool = None, verified: bool = None,
                  compute_cap: int = None, min_pcie_gen: int = None,
                  static_ip: bool = None, offer_type: str = None,
                  geolocation_exclude: List[str] = None, num_gpus: int = None,
                  min_disk: int = None, allocated_storage: int = None) -> List[Dict[str, Any]]:
    """Return a list of offers matching advanced constraints, sorted by price ascending.

    Args:
        min_vram: Minimum GPU VRAM in GB
        max_price: Maximum price per hour in USD
        limit: Max number of offers to return
        min_price: Minimum price per hour (filters out too cheap/slow GPUs)
        min_reliability: Minimum reliability score (0-1)
        gpu_models: List of acceptable GPU model names (e.g., ["RTX_3090", "RTX_4080"])
        min_cuda: Minimum CUDA version (e.g., 11.2)
        min_dlperf: Minimum deep learning performance score
        min_dlperf_per_dphtotal: Minimum DL performance per dollar per hour
        min_inet_down: Minimum download bandwidth in MB/s
        min_inet_up: Minimum upload bandwidth in MB/s
        min_cpu_cores: Minimum CPU cores
        min_cpu_ram: Minimum CPU RAM in GB
        min_disk_bw: Minimum disk bandwidth in MB/s
        min_gpu_mem_bw: Minimum GPU memory bandwidth in GB/s
        datacenter: Filter for datacenter offers only
        verified: Filter for verified hosts only
        compute_cap: Minimum CUDA compute capability * 100 (e.g., 700 for 7.0)
        min_pcie_gen: Minimum PCIe generation (e.g., 4)
        static_ip: Filter for static IP addresses
        offer_type: Instance type: "bid", "on-demand", or "reserved"
        geolocation_exclude: List of country codes to exclude (e.g., ["CN", "RU"])

    The actual endpoint parameters may vary; we try commonly used query keys.
    If /market/offers fails or returns unexpected content, fall back to PUT /search/asks/ (console API).
    """
    params = {
        "min_gpu_mem": min_vram,
        "max_price": max_price,
        "limit": limit,
        "sort": "price",
    }
    try:
        data = api_get("/market/offers", params=params)
    except Exception as e:
        # fallback: try search/asks route (PUT) which some console endpoints support
        try:
            payload = {
                "select_cols": ["*"],
                "q": {
                    "rentable": {"eq": True},
                    "limit": limit,
                    "order": [["dph_total", "asc"]],
                    # interpret min_vram (GB) as gpu_ram in MB
                    "gpu_ram": {"gte": int(min_vram * 1024)}
                }
            }

            # Add advanced filters to query
            if min_price is not None:
                payload["q"]["dph_total"] = {"gte": min_price}
            if min_reliability is not None:
                payload["q"]["reliability2"] = {"gte": min_reliability}
            if gpu_models:
                # Convert GPU names to API format (spaces to underscores)
                api_models = [m.replace(" ", "_") for m in gpu_models]
                payload["q"]["gpu_name"] = {"in": api_models}
            if min_cuda is not None:
                payload["q"]["cuda_max_good"] = {"gte": min_cuda}
            if min_dlperf is not None:
                payload["q"]["dlperf"] = {"gte": min_dlperf}
            if min_dlperf_per_dphtotal is not None:
                payload["q"]["dlperf_per_dphtotal"] = {"gte": min_dlperf_per_dphtotal}
            if min_inet_down is not None:
                payload["q"]["inet_down"] = {"gte": min_inet_down}
            if min_inet_up is not None:
                payload["q"]["inet_up"] = {"gte": min_inet_up}
            if min_cpu_cores is not None:
                payload["q"]["cpu_cores"] = {"gte": min_cpu_cores}
            if min_cpu_ram is not None:
                # Convert GB to MB
                payload["q"]["cpu_ram"] = {"gte": int(min_cpu_ram * 1024)}
            if min_disk_bw is not None:
                payload["q"]["disk_bw"] = {"gte": min_disk_bw}
            if min_gpu_mem_bw is not None:
                payload["q"]["gpu_mem_bw"] = {"gte": min_gpu_mem_bw}
            if min_disk is not None:
                # Many API variants accept 'disk' or similar; request hosts with at least this much disk (GB)
                try:
                    payload["q"]["disk"] = {"gte": int(min_disk)}
                except Exception:
                    payload["q"]["disk"] = {"gte": min_disk}
            if allocated_storage is not None:
                # Some interfaces support allocated_storage as requested disk; include it as top-level hint
                try:
                    payload["allocated_storage"] = int(allocated_storage)
                except Exception:
                    payload["allocated_storage"] = allocated_storage
            if datacenter is not None:
                payload["q"]["datacenter"] = {"eq": datacenter}
            if verified is not None:
                payload["q"]["verified"] = {"eq": verified}
            if compute_cap is not None:
                payload["q"]["compute_cap"] = {"gte": compute_cap}
            if min_pcie_gen is not None:
                payload["q"]["pci_gen"] = {"gte": min_pcie_gen}
            if static_ip is not None:
                payload["q"]["static_ip"] = {"eq": static_ip}
            if offer_type is not None:
                payload["type"] = offer_type
            if geolocation_exclude:
                payload["q"]["geolocation"] = {"nin": geolocation_exclude}
            if num_gpus is not None:
                payload["q"]["num_gpus"] = {"eq": num_gpus}
            # try both API_BASE and fallback base
            attempted = []
            alt = os.environ.get("VAST_API_FALLBACK", "https://console.vast.ai/api/v0")
            bases = [API_BASE]
            if alt and alt.rstrip('/') not in [b.rstrip('/') for b in bases]:
                bases.append(alt)
            last_exc = None
            for base in bases:
                attempted.append(base)
                url = f"{base.rstrip('/')}/search/asks/"
                try:
                    r = requests.put(url, headers=HEADERS, json=payload, timeout=30)
                    r.raise_for_status()
                    res = r.json()
                    # try common shapes
                    if isinstance(res, dict):
                        if 'offers' in res and isinstance(res['offers'], list):
                            return res['offers']
                        for k in ('data', 'results', 'asks'):
                            if k in res and isinstance(res[k], list):
                                return res[k]
                    if isinstance(res, list):
                        return res
                except Exception as ex:
                    last_exc = ex
                    continue
            raise RuntimeError(f"Fallback search/asks failed. Attempted: {attempted}. Last error: {last_exc}") from last_exc
        except Exception:
            # re-raise original exception to keep behavior
            raise

    # Some API variants return a dict with key 'offers' or list directly.
    if isinstance(data, dict):
        if "offers" in data:
            return data["offers"]
        # fallback: return values if it looks like a list
        for k in ("data", "results"):
            if k in data and isinstance(data[k], list):
                return data[k]
    if isinstance(data, list):
        return data
    # unknown shape -> return empty
    return []


def pick_offer(offers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not offers:
        return None

    # Blacklist of problematic hosts (CDI device errors, old drivers, etc.)
    # Start with built-in blacklist and extend with config-specified host blacklist
    BLACKLISTED_HOSTS = [
        67349,  # fiber1.kmidata.es - Spain (CDI device errors with slim image)
    ]
    # extend with values loaded from config.yaml (VAST_HOST_BLACKLIST)
    try:
        for h in VAST_HOST_BLACKLIST:
            if h not in BLACKLISTED_HOSTS:
                BLACKLISTED_HOSTS.append(int(h))
    except Exception:
        pass

    # GPU blacklist - old/weak GPUs that can't handle modern processing
    BLACKLISTED_GPUS = [
        'GTX 1070', 'GTX 1070 Ti', 'GTX 1080', 'GTX 1080 Ti',  # Maxwell/Pascal - too old
        'GTX 1660', 'GTX 1650',  # Turing budget - too weak
        'RTX 2060',  # Turing entry - marginal for 4K
    ]

    # Mobile/Laptop GPU markers - exclude these (weaker than desktop)
    MOBILE_MARKERS = [
        'Mobile', 'Laptop', 'Max-Q', 'laptop',  # Mobile variants
        'Ti Laptop', 'Laptop GPU',  # Explicit laptop
    ]

    # Preferred modern GPUs (RTX 30xx, 40xx, A-series) - DESKTOP ONLY
    PREFERRED_GPUS = [
        'RTX 3060', 'RTX 3070', 'RTX 3080', 'RTX 3090',
        'RTX 4060', 'RTX 4070', 'RTX 4080', 'RTX 4090',
        'RTX A4000', 'RTX A5000', 'RTX A6000',
        'A100', 'A40', 'A30',
    ]

    # Filter out blacklisted hosts and weak GPUs
    filtered_offers = []
    for offer in offers:
        host_id = offer.get('host_id')
        if host_id in BLACKLISTED_HOSTS:
            continue  # Skip this host

        # Check GPU name
        gpu_name = offer.get('gpu_name', '')

        # Skip mobile/laptop GPUs
        if any(marker in gpu_name for marker in MOBILE_MARKERS):
            continue  # Skip mobile/laptop GPU

        # Skip if GPU is blacklisted
        if any(blacklisted in gpu_name for blacklisted in BLACKLISTED_GPUS):
            continue  # Skip weak/old GPU

        # Prefer verified hosts with good reliability
        reliability = offer.get('reliability2', 0)
        if reliability >= 0.95 or offer.get('verification') == 'verified':
            filtered_offers.append(offer)
        elif reliability >= 0.90:  # Accept decent reliability as fallback
            filtered_offers.append(offer)

    # If filtering removed all offers, try again with just host blacklist (allow old GPUs as fallback)
    if not filtered_offers:
        print("⚠️  No modern GPUs found, falling back to any available GPU...")
        filtered_offers = [o for o in offers if o.get('host_id') not in BLACKLISTED_HOSTS]

    if not filtered_offers:
        return None

    # Prioritize preferred GPUs
    preferred = [o for o in filtered_offers if any(pref in o.get('gpu_name', '') for pref in PREFERRED_GPUS)]
    if preferred:
        offers = preferred
    else:
        offers = filtered_offers

    def get_price(o: Dict[str, Any]) -> float:
        # Try common price fields and coerce to float, fallback to a large number
        for k in ("price_per_hour", "price", "hourly_price", "price_usd", "price_hourly"):
            v = o.get(k)
            if v is None:
                continue
            try:
                return float(v)
            except Exception:
                # sometimes price is nested or a string like '$0.12' — try to extract digits
                try:
                    s = str(v)
                    s = s.replace('$', '').replace(',', '').strip()
                    return float(s)
                except Exception:
                    continue
        # fallback: try 'pricing' subfields
        p = o.get('pricing') or o.get('price_info') or {}
        if isinstance(p, dict):
            # find first numeric value
            for val in p.values():
                try:
                    return float(val)
                except Exception:
                    continue
        return float('inf')

    # Choose offer with minimum numeric price
    best = min(offers, key=get_price)
    return best


def create_instance(offer_id: str, image: str, cmd: str, env: Optional[Dict[str, str]] = None, 
                    start: bool = True, max_hours: float = 24.0, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create an instance by accepting an ask (offer) using PUT /asks/{id}/ as per the current Vast API.
    The `cmd` argument is passed as `args_str` (shell command) unless `options` contains `args`.
    """
    payload: Dict[str, Any] = {}
    payload['image'] = image
    # map the command string to args_str by default
    if cmd:
        payload['args_str'] = cmd
    # merge env
    if env:
        payload['env'] = env

    # set target_state based on start unless explicitly provided
    if options and 'target_state' in options:
        payload['target_state'] = options.get('target_state')
    else:
        payload['target_state'] = 'running' if start else 'stopped'

    # merge other known options if provided
    if options:
        for k in ('price', 'label', 'disk', 'runtype', 'cancel_unavail', 'vm', 'onstart', 'args', 'args_str', 'template_id', 'template_hash_id', 'volume_info'):
            if k in options and options[k] is not None:
                payload[k] = options[k]

    print("Creating instance (accept ask) with payload:\n", payload)
    # Use PUT /asks/{id}/ to accept the ask
    try:
        inst = api_put(f"/asks/{offer_id}/", payload)
        return inst
    except Exception as e:
        # fallback: try older POST /instances for compatibility
        print('PUT /asks failed, attempting fallback to POST /instances:', e)
        fallback = {
            'offer_id': offer_id,
            'image': image,
            'cmd': cmd,
            'env': env or {},
            'max_hours': max_hours,
        }
        inst = api_post('/instances', fallback)
        return inst


def get_instance(instance_id: str) -> Dict[str, Any]:
    return api_get(f"/instances/{instance_id}")


def _extract_status_from_instance(inst: Dict[str, Any]) -> Optional[str]:
    # inst may be a dict with nested 'instances' key or top-level fields.
    if not isinstance(inst, dict):
        return None
    # If API wrapped under 'instances'
    data = inst.get('instances') if 'instances' in inst else inst
    if isinstance(data, dict):
        # check common status fields
        for key in ('status', 'cur_state', 'actual_status', 'state', 'intended_status', 'next_state'):
            v = data.get(key)
            if isinstance(v, str) and v:
                return v
    # last-resort: top-level keys
    for key in ('status', 'cur_state', 'actual_status', 'state', 'intended_status'):
        v = inst.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def wait_for_status(instance_id: str, desired: List[str], timeout: int = 600, poll: int = 3) -> Dict[str, Any]:
    print(f"Waiting for instance {instance_id} to enter one of {desired} (timeout {timeout}s)...")
    start = time.time()
    last_status = None
    while True:
        inst = get_instance(instance_id)
        status = _extract_status_from_instance(inst)
        print(f"  status={status}")
        last_status = status
        if status in desired:
            return inst
        if time.time() - start > timeout:
            raise TimeoutError(f"Timeout waiting for instance {instance_id} status {desired}. Last status: {last_status}")
        time.sleep(poll)


def delete_instance(instance_id: str) -> Dict[str, Any]:
    url = f"{API_BASE}/instances/{instance_id}/delete"
    r = requests.post(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def stop_instance(instance_id: str) -> Dict[str, Any]:
    """Stop (pause) a running instance"""
    url = f"{API_BASE}/instances/{instance_id}/"
    payload = {"state": "stopped"}
    r = requests.put(url, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def start_instance(instance_id: str) -> Dict[str, Any]:
    """Start a stopped instance"""
    url = f"{API_BASE}/instances/{instance_id}/"
    payload = {"state": "running"}
    r = requests.put(url, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def destroy_instance(instance_id: str) -> Dict[str, Any]:
    """Permanently destroy an instance"""
    url = f"{API_BASE}/instances/{instance_id}/"
    r = requests.delete(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def human_offer_summary(o: Dict[str, Any]) -> str:
    price = o.get("price_per_hour") or o.get("price") or o.get("hourly_price") or "?"
    gpu = o.get("gpu") or o.get("gpu_model") or o.get("device") or "?"
    vram = o.get("vram") or o.get("gpu_mem") or o.get("mem_gpu") or "?"
    region = o.get("region") or o.get("location") or "?"
    return f"offer_id={o.get('id')} gpu={gpu} vram={vram} price/hr={price} region={region}"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Submit a processing job to vast.ai via HTTP API.")
    parser.add_argument("--image", required=False, help="Docker image to run on the remote instance (e.g. myrepo/myimage:latest)")
    parser.add_argument("--cmd", required=False, help="Command to run inside the container. Use /workspace/input.mp4 as input path in your command if you pass --input-url. Required unless --cheap-test is used.")
    parser.add_argument("--input-url", required=False, help="Public HTTP(S) URL of the input file. If provided, the created command can wget/curl it on the instance.")
    # Backblaze B2 (S3-compatible) presign automation
    parser.add_argument("--b2-bucket", help="Backblaze B2 bucket name (S3-compatible). If provided, presigned URLs will be generated locally.")
    parser.add_argument("--b2-key", help="Object key/path for input file in the bucket (e.g. input/test_60_short.mp4)")
    parser.add_argument("--b2-out-key", help="(optional) Object key/path for output file (default: out/<b2-key>)")
    parser.add_argument("--b2-endpoint", help="(optional) S3-compatible endpoint for Backblaze (defaults to B2_ENDPOINT env or us-west)")
    parser.add_argument("--b2-region", help="(optional) region name for B2 client")
    parser.add_argument("--b2-expires", type=int, default=604800, help="Presigned URL expiry in seconds (default: 1 week)")
    parser.add_argument("--local-file", help="(optional) Local file path to upload to B2 before creating instance")
    parser.add_argument("--b2-overwrite", action="store_true", help="Force upload and overwrite existing object in B2")
    parser.add_argument("--min-vram", type=int, default=4, help="Minimum GPU VRAM (GB) required")
    parser.add_argument("--max-price", type=float, default=0.5, help="Maximum price per hour in USD")
    parser.add_argument("--limit", type=int, default=30, help="How many offers to fetch")
    parser.add_argument("--wait-running", action="store_true", help="Wait until the instance becomes running")
    parser.add_argument("--wait-finish", action="store_true", help="Wait until instance status is terminated and print final info")
    parser.add_argument("--max-hours", type=float, default=6.0, help="Max allowed hours for estimate")
    parser.add_argument("--no-start", action="store_true", help="Create instance but don't start the container (if supported by API)")
    parser.add_argument("--offer-id", help="(optional) Use a specific offer id and skip searching the market")
    parser.add_argument("--host-id", type=int, help="(optional) Filter offers to only this host_id (for Docker image caching)")
    parser.add_argument("--offline", action="store_true", help="Skip searching vast.ai market (use --offer-id) — useful if api.vast.ai is unreachable from this host")
    parser.add_argument("--cheap-test", action="store_true", help="Run a short, cheap smoke-test: small min-vram, low max-price, tiny max-hours and a short download+ffprobe command (requires --b2-bucket/--b2-key or --input-url)")
    parser.add_argument("--list-offers", action="store_true", help="List a few cheapest offers matching constraints and exit")
    parser.add_argument("--list-count", type=int, default=10, help="How many offers to list when --list-offers is used")
    args = parser.parse_args(argv)

    # If user requested only to list offers, perform search and exit early (bypass --cmd / --image checks)
    if getattr(args, 'list_offers', False):
        print(f"Listing up to {args.list_count} offers matching min_vram={args.min_vram}, max_price={args.max_price}")
        try:
            offers = search_offers(min_vram=args.min_vram, max_price=args.max_price, limit=args.limit)
        except Exception as e:
            print('Error searching offers:', e)
            return 4
        if not offers:
            print('No offers found matching constraints.')
            return 0
        # Apply host blacklist from config (if present) so --list-offers respects same exclusions as pick_offer
        try:
            if VAST_HOST_BLACKLIST:
                orig = len(offers)
                offers = [o for o in offers if o.get('host_id') not in VAST_HOST_BLACKLIST]
                print(f"Info: applied host blacklist from config: {VAST_HOST_BLACKLIST} — filtered {orig} → {len(offers)} offers")
                if not offers:
                    print('No offers remain after applying host blacklist.')
                    return 0
        except Exception:
            # non-fatal — continue without blacklist if something unexpected in offers
            pass
        # sort offers by numeric price for stable ordering
        def _price(o: Dict[str, Any]) -> float:
            for k in ("price_per_hour", "price", "hourly_price", "price_usd", "price_hourly"):
                v = o.get(k)
                if v is None:
                    continue
                try:
                    return float(v)
                except Exception:
                    s = str(v).replace('$','').replace(',','').strip()
                    try:
                        return float(s)
                    except Exception:
                        continue
            p = o.get('pricing') or o.get('price_info') or {}
            if isinstance(p, dict):
                for val in p.values():
                    try:
                        return float(val)
                    except Exception:
                        continue
            return float('inf')

        offers_sorted = sorted(offers, key=_price)
        for i, off in enumerate(offers_sorted[:args.list_count], start=1):
            print(f"{i}. {human_offer_summary(off)}")
        return 0

    # If user only wants to list offers, image is not required. Otherwise, require --image to create instance.
    if not getattr(args, 'list_offers', False) and not args.image and not args.cheap_test:
        parser.error("the following arguments are required: --image (unless --list-offers or --cheap-test is used)")

    # Validate: --cmd is required unless --cheap-test is used (which supplies its own short test cmd)
    if not args.cmd and not args.cheap_test and not getattr(args, 'list_offers', False):
        parser.error("the following arguments are required: --cmd (unless --cheap-test or --list-offers is used)")

    # Build the command to run inside the container
    run_cmd_str = args.cmd

    # If cheap-test requested, build a short smoke test command that downloads the input and runs ffprobe
    if args.cheap_test:
        # cheap-test requires either an input URL or B2 bucket/key so we can generate a presigned GET
        if not args.input_url and not (args.b2_bucket and args.b2_key):
            parser.error("--cheap-test requires either --input-url or --b2-bucket and --b2-key")

        if args.input_url:
            get_url = args.input_url
        else:
            # Try to call local b2_presign.py to generate a GET URL
            try:
                import subprocess, json
                script_dir = os.path.dirname(__file__)
                presign = os.path.join(script_dir, 'b2_presign.py')
                out = subprocess.check_output([sys.executable, presign, '--bucket', args.b2_bucket, '--key', args.b2_key, '--endpoint', args.b2_endpoint or os.environ.get('B2_ENDPOINT', ''), '--expires', str(args.b2_expires)], universal_newlines=True)
                get_url = json.loads(out).get('get_url')
                if not get_url:
                    raise RuntimeError('b2_presign.py did not return get_url')
            except Exception as e:
                print('Failed to generate presigned GET URL for cheap-test:', e)
                return 3

        # simple command: download and ffprobe (non-failing)
        run_cmd_str = f"bash -lc 'wget -O /workspace/input.mp4 \"{get_url}\" && ffprobe -v error /workspace/input.mp4 || true'"

    # At this point we must have a run command
    if not run_cmd_str:
        parser.error("No command to run inside container; provide --cmd or use --cheap-test")

    # Determine offer id: explicit --offer-id, or search the market
    chosen_offer_id = None
    chosen_offer = None
    if args.offer_id:
        chosen_offer_id = args.offer_id
    else:
        if args.offline:
            parser.error('--offline requires --offer-id to be set')
        print(f"Searching market for offers (min_vram={args.min_vram}GB, max_price=${args.max_price}/hr, limit={args.limit})...")
        try:
            offers = search_offers(min_vram=args.min_vram, max_price=args.max_price, limit=args.limit)
        except Exception as e:
            print('Error searching offers:', e)
            return 4

        if not offers:
            print('No offers found matching constraints.')
            return 5

        # Filter by host_id if specified
        if args.host_id:
            print(f'Filtering offers to host_id={args.host_id}...')
            original_count = len(offers)
            offers = [o for o in offers if o.get('host_id') == args.host_id]
            print(f'  Filtered: {original_count} → {len(offers)} offers')

            if not offers:
                print(f'No offers found on host_id={args.host_id}')
                print('Host may be offline or not available. Try without --reuse-host.')
                return 5

        chosen_offer = pick_offer(offers)
        if not chosen_offer:
            print('Failed to pick an offer (empty list).')
            return 6

        print('Selected offer:', human_offer_summary(chosen_offer))
        # try common id keys
        chosen_offer_id = str(chosen_offer.get('id') or chosen_offer.get('offer_id') or chosen_offer.get('offer'))

    if not chosen_offer_id:
        print('Could not determine offer id to use.')
        return 7

    # Create the instance
    env = {}
    # pass input URL via env so container can access if desired
    if args.input_url:
        env['INPUT_URL'] = args.input_url
    # also expose b2_* params so user command inside container may use them
    if args.b2_bucket:
        env['B2_BUCKET'] = args.b2_bucket
    if args.b2_key:
        env['B2_KEY'] = args.b2_key
    if args.b2_endpoint:
        env['B2_ENDPOINT'] = args.b2_endpoint

    # If user provided a local file to upload, attempt an idempotent upload (skip if exists with same size)
    if args.local_file and args.b2_bucket and args.b2_key:
        try:
            # Import upload helper lazily to avoid hard dependency unless used
            try:
                import upload_b2
            except Exception:
                upload_b2 = None
            if upload_b2 is None:
                print('Warning: upload_b2 helper not available; skipping local upload. Install boto3 to enable uploads.')
            else:
                access = os.environ.get('B2_KEY')
                secret = os.environ.get('B2_SECRET')
                endpoint = args.b2_endpoint or os.environ.get('B2_ENDPOINT')
                region = args.b2_region or os.environ.get('B2_REGION')
                print(f"Uploading local file '{args.local_file}' -> s3://{args.b2_bucket}/{args.b2_key} (overwrite={args.b2_overwrite}) ...")
                get_url = upload_b2.upload_file(args.local_file, args.b2_bucket, args.b2_key, access, secret, endpoint, region, expires=args.b2_expires, overwrite=args.b2_overwrite)
                print('Upload step finished. Presigned GET:', get_url)
                # Ensure instance has INPUT_URL env so container can access it if desired
                env['INPUT_URL'] = get_url
                # If user did not already include a download in their cmd and provided a local file, prepend download step
                if args.input_url is None:
                    # Safely wrap the existing command so remote will download the input to /workspace/input.mp4 first
                    original = run_cmd_str
                    # Use bash -lc wrapper; if original already contains complex quoting this is best-effort
                    run_cmd_str = f"bash -lc 'wget -O /workspace/input.mp4 \"{get_url}\" || curl -L -o /workspace/input.mp4 \"{get_url}\"; {original}'"
        except Exception as e:
            print('Failed during local-file upload step:', e)
            # proceed without failing — user can still provide input_url or b2 params

    try:
        inst = create_instance(offer_id=chosen_offer_id, image=args.image, cmd=run_cmd_str, env=env, start=(not args.no_start), max_hours=args.max_hours)
    except Exception as e:
        print('Failed to create instance:', e)
        return 8

    # Try to extract a usable instance/contract id from common response fields
    inst_id = None
    if isinstance(inst, dict):
        for key in ("id", "instance_id", "_id", "uuid", "name", "contract", "contract_id", "new_contract", "new_contract_id"):
            if key in inst and inst.get(key):
                inst_id = str(inst.get(key))
                break
        # Some responses nest created object under 'result' or similar
        if not inst_id:
            for k in ("result", "instance", "instances", "data"):
                v = inst.get(k)
                if isinstance(v, dict):
                    for key in ("id", "instance_id", "_id", "uuid", "name", "contract", "contract_id", "new_contract"):
                        if key in v and v.get(key):
                            inst_id = str(v.get(key))
                            break
                if inst_id:
                    break

    print("Instance created:")
    print(inst)
    if not inst_id:
        print("Warning: could not determine instance id from API response. Raw response above.")
        # fail early to avoid passing None to wait_for_status
        return 0

    print("Using instance id:", inst_id)

    if args.wait_running and inst_id:
        try:
            run_inst = wait_for_status(inst_id, ["running", "ready"], timeout=300)
            print("Instance running info:\n", run_inst)
        except Exception as e:
            print("Error while waiting for running:", e)

    # Optionally wait until instance terminates
    if args.wait_finish:
        try:
            inst = wait_for_status(str(inst_id), ['terminated'], timeout=int(args.max_hours * 3600) + 600, poll=10)
            print('Instance finished:')
            print(inst)
        except Exception as e:
            print('Error waiting for instance to finish:', e)

    print('Done.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
