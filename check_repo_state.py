import os
import json
import importlib

checks = [
    'pipeline.py',
    'scripts/entrypoint.sh',
    'scripts/remote_runner.sh',
    'scripts/container_config_runner.py',
    'scripts/container_upload.py',
    'scripts/run_with_config_batch_sync.py',
    'b2_presign.py',
    'upload_b2.py',
    'vast_submit.py',
    'monitor_instance.py',
    'Dockerfile.pytorch.fat',
    'requirements.txt',
    'config.yaml',
    'RIFEv4.26_0921'
]
mods = [
    'scripts.run_with_config_batch_sync',
    'scripts.run_slim_vast',
    'scripts.container_config_runner',
    'pipeline',
    'b2_presign',
    'upload_b2',
    'vast_submit'
]

result = {'exists': {}, 'imports': {}, 'manifest_count': None}
for p in checks:
    result['exists'][p] = os.path.exists(p)

# manifest
manifest_path = os.path.join('trash', '.trash-moved.json')
if os.path.exists(manifest_path):
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            result['manifest_count'] = len(data)
    except Exception as e:
        result['manifest_count'] = f'error: {e}'
else:
    result['manifest_count'] = 'missing'

# imports
for m in mods:
    try:
        importlib.import_module(m)
        result['imports'][m] = 'ok'
    except Exception as e:
        result['imports'][m] = repr(e)

print(json.dumps(result, indent=2, ensure_ascii=False))

