"""Fake serverless child for CPU tests. FAKE_CHILD=ok|sleep|cuda. Spec format = src/serverless/child.py."""

import json
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

spec = json.loads(Path(sys.argv[1]).read_text())
mode = os.environ.get("FAKE_CHILD", "ok")
if mode == "sleep":
    # a grandchild like ffmpeg: must die with the group
    p = subprocess.Popen(["sleep", "120"])
    Path(spec["dst"]).with_suffix(".pid").write_text(str(p.pid))
    time.sleep(120)
if mode == "cuda":
    print(
        "RuntimeError: CUDA error: no kernel image is available for execution on the device",
        flush=True,
    )
    sys.exit(1)
subprocess.run(
    [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=30:duration=1",
        "-vf",
        "fps=60",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        spec["dst"],
    ],
    check=True,
)
print("x Assembling video with encoder: libx264", flush=True)
Path(spec["result_path"]).write_text(
    json.dumps(
        {
            "timings": {"input_s": 0, "pipeline_s": 0.1},
            "input_sha256": hashlib.sha256(b"synthetic-input").hexdigest(),
            "input_duration_s": 1.0,
        }
    )
)
