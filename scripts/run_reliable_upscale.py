#!/usr/bin/env python3
"""
scripts/run_reliable_upscale.py

Create an instance that runs the pipeline and uploads result to B2 using boto3 and env creds.
Usage: python scripts/run_reliable_upscale.py

This script uses VAST_API_KEY and B2 credentials from .env or environment.
"""
import os, sys, time, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ensure .env loaded same way as vast_submit
_env = ROOT / '.env'
if _env.exists():
    try:
        import importlib
        _mod = importlib.import_module('dotenv')
        _load = getattr(_mod, 'load_dotenv')
        _load(dotenv_path=str(_env))
    except Exception:
        with open(_env, 'r', encoding='utf-8') as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith('#') or l.startswith('//'):
                    continue
                if '=' not in l:
                    continue
                k,v = l.split('=',1)
                k=k.strip(); v=v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k]=v

# import vast_submit
import vast_submit

# Public (short) URLs for runner and input — we rely on these being public in the bucket
RUNNER_URL = os.environ.get('RUNNER_PUBLIC') or 'https://noxfvr-videos.s3.us-west-004.backblazeb2.com/scripts/remote_runner.sh'
INPUT_URL = os.environ.get('INPUT_PUBLIC') or 'https://noxfvr-videos.s3.us-west-004.backblazeb2.com/input/qad.mp4'
# B2 target key prefix
OUT_KEY_PREFIX = os.environ.get('B2_OUT_PREFIX','output')

# budget / offer selection
MIN_VRAM = int(os.environ.get('MIN_VRAM', '8'))
MAX_PRICE = float(os.environ.get('MAX_PRICE', '0.08'))

print('Searching offers min_vram=', MIN_VRAM, 'max_price=', MAX_PRICE)
offers = vast_submit.search_offers(min_vram=MIN_VRAM, max_price=MAX_PRICE, limit=300)
print('Offers found:', len(offers))
# filter candidates: non-laptop, single GPU, prefer 4060 family
candidates = []
for o in offers:
    gpu = (o.get('gpu') or o.get('gpu_name') or o.get('device') or o.get('name') or '')
    if not isinstance(gpu, str):
        gpu = str(gpu)
    glower = gpu.replace('-', ' ').lower()
    if 'laptop' in glower or 'mobile' in glower:
        continue
    num_gpus = o.get('num_gpus') or o.get('num_gpu') or o.get('gpus') or 1
    try:
        if int(num_gpus) != 1:
            continue
    except Exception:
        pass
    # price
    price = None
    for k in ('dph_total','price_per_hour','price','hourly_price'):
        if k in o and o[k] is not None:
            try:
                price = float(o[k])
            except Exception:
                try:
                    price = float(str(o[k]).replace('$','').replace(',',''))
                except Exception:
                    price = None
            break
    if price is None:
        continue
    if price > MAX_PRICE:
        continue
    # perf metric
    perf = None
    try:
        perf = float(o.get('dlperf_per_dphtotal') or o.get('dlperf') or o.get('total_flops') or 0)
    except Exception:
        perf = 0.0
    candidates.append((o, price, perf, glower))

chosen = None
if candidates:
    # prefer 4060 family if present
    fam = [c for c in candidates if '4060' in c[3]]
    pool = fam if fam else candidates
    # sort by perf desc then price asc
    pool.sort(key=lambda x: (x[2], -x[1]), reverse=True)
    chosen = pool[0][0]
else:
    print('No candidates in price band; falling back to cheapest overall offer (may exceed budget)')
    chosen = vast_submit.pick_offer(offfers := offers or [])

if not chosen:
    print('No offer chosen; aborting')
    sys.exit(1)

print('Chosen offer:', vast_submit.human_offer_summary(chosen))
offer_id = str(chosen.get('id') or chosen.get('offer_id') or chosen.get('offer'))

# Build args_str: download runner and input (public), run runner to produce /workspace/output/output_upscaled.mp4,
# then run small Python uploader that uses boto3 and env creds to upload file to B2 bucket under OUT_KEY_PREFIX
import datetime
ts = int(time.time())
out_key = f"{OUT_KEY_PREFIX}/qad_upscaled_{ts}.mp4"

uploader_py = r"""
import os
import sys
try:
    import boto3
    from botocore.client import Config
except Exception:
    print('boto3 missing, attempting pip install')
    os.system('python -m pip install --no-cache-dir boto3 botocore')
    import boto3
    from botocore.client import Config

B2_KEY = os.environ.get('B2_KEY')
B2_SECRET = os.environ.get('B2_SECRET')
B2_BUCKET = os.environ.get('B2_BUCKET')
B2_ENDPOINT = os.environ.get('B2_ENDPOINT')
if not B2_KEY or not B2_SECRET or not B2_BUCKET or not B2_ENDPOINT:
    print('Missing B2 credentials in env')
    sys.exit(2)

s3 = boto3.client('s3', endpoint_url=B2_ENDPOINT, aws_access_key_id=B2_KEY, aws_secret_access_key=B2_SECRET, config=Config(s3={'addressing_style':'virtual'}))
local = '/workspace/output/output_upscaled.mp4'
if not os.path.exists(local):
    print('No output file to upload:', local)
    sys.exit(3)
try:
    s3.upload_file(local, B2_BUCKET, '%s')
    print('UPLOAD_DONE %s')
except Exception as e:
    print('UPLOAD_FAILED', e)
    sys.exit(4)
""".replace('%s', out_key)

# args_str assembly: use bash -lc and a heredoc for the python uploader to avoid quoting issues
args_str = (
    "bash -lc 'set -euo pipefail; "
    f"wget -O /workspace/runner.sh \"{RUNNER_URL}\" && chmod +x /workspace/runner.sh && "
    f"wget -O /workspace/input.mp4 \"{INPUT_URL}\" && /workspace/runner.sh /workspace/input.mp4 /workspace/output || true; "
    "cat > /workspace/_uploader.py <<\'PY\'\n" + uploader_py + "\nPY\n" + "python /workspace/_uploader.py" + "'"
)

print('Creating instance with args_str length', len(args_str))
# prepare env to pass to instance
env = {
    'B2_KEY': os.environ.get('B2_KEY',''),
    'B2_SECRET': os.environ.get('B2_SECRET',''),
    'B2_BUCKET': os.environ.get('B2_BUCKET',''),
    'B2_ENDPOINT': os.environ.get('B2_ENDPOINT',''),
}
# also pass AWS_* for compatibility
env['AWS_ACCESS_KEY_ID'] = env['B2_KEY']
env['AWS_SECRET_ACCESS_KEY'] = env['B2_SECRET']

print('Env keys to pass: B2_BUCKET=', env.get('B2_BUCKET') is not None)

print('Calling create_instance...')
try:
    resp = vast_submit.create_instance(offer_id, os.environ.get('VAST_IMAGE',''), args_str, env=env, start=True)
    print('Create response:', json.dumps(resp, indent=2))
except Exception as e:
    print('Create failed:', e)
    sys.exit(5)

inst_id = str(resp.get('new_contract') or resp.get('id') or resp.get('instance_id'))
print('Instance id:', inst_id)

# wait for running
try:
    vast_submit.wait_for_status(inst_id, ['running'], timeout=600, poll=5)
    print('Instance running')
except Exception as e:
    print('Instance did not reach running:', e)

# poll logs up to 20 minutes
end = time.time() + 20*60
found = False
last = ''
while time.time() < end:
    try:
        r = vast_submit.api_put(f"/instances/request_logs/{inst_id}/", {'tail': '500'})
    except Exception as e:
        print('request_logs failed', e)
        time.sleep(8)
        continue
    url = r.get('result_url') or r.get('url')
    if url:
        try:
            import requests
            rr = requests.get(url, timeout=30)
            txt = rr.text
            print('log tail snippet:', txt[-300:])
            last = txt
            if 'UPLOAD_DONE' in txt:
                print('Detected UPLOAD_DONE')
                found = True
                break
        except Exception as e:
            print('fetch failed', e)
    time.sleep(8)

print('Finished polling, found=', found)
if found:
    # provide GET URL for uploaded object
    get_url = f"{env['B2_ENDPOINT'].rstrip('/')}/{env['B2_BUCKET']}/{out_key}"
    print('Result available at (public GET may require presign):', get_url)
else:
    print('Logs last snippet:', last[-800:])

print('Done')

