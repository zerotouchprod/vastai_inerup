#!/usr/bin/env python3
import sys
sys.path.insert(0, 'src')
from dotenv import load_dotenv
load_dotenv()
from infrastructure.vastai.client import VastAIClient

print("Testing log fetching...", flush=True)

try:
    client = VastAIClient()
    print("Client created", flush=True)
    
    logs = client.get_instance_logs(28422904, tail=1000)
    print(f"Logs fetched", flush=True)
    
    print(f"\nType: {type(logs)}", flush=True)
    print(f"Length: {len(logs) if logs is not None else 'None'}", flush=True)
    print(f"Bool: {bool(logs)}", flush=True)
    print(f"Is None: {logs is None}", flush=True)
    print(f"Is empty string: {logs == ''}", flush=True)
    
    if logs:
        lines = logs.split('\n')
        print(f"\nTotal lines: {len(lines)}", flush=True)
        print(f"\nFirst 10 lines:", flush=True)
        for i, line in enumerate(lines[:10]):
            print(f"  {i+1}: {line[:100]}", flush=True)
    else:
        print("\n❌ Logs are falsy (empty or None)!", flush=True)
        
except Exception as e:
    print(f"ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()

