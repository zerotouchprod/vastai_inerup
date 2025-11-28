#!/usr/bin/env python3
"""Simple runner to test FrameExtractor in-container.
Usage:
  python3 scripts/run_extractor_test.py /path/to/input.mp4 /tmp/extractor_test_dir --pad 32

Outputs JSON summary to stdout and writes extractor logs to <dest_dir>/extractor.log
"""
import sys
import os
import json
import traceback
from dataclasses import asdict

from src.io.extractor import FrameExtractor


def main(argv):
    if len(argv) < 2:
        print("Usage: run_extractor_test.py <input_video> <dest_dir> [--pad N]")
        return 2
    input_path = argv[1]
    dest_dir = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else "/tmp/extractor_test"
    # parse optional --pad
    pad_to = 32
    if "--pad" in argv:
        try:
            i = argv.index("--pad")
            pad_to = int(argv[i+1])
        except Exception:
            pass

    os.makedirs(dest_dir, exist_ok=True)
    extractor = FrameExtractor()
    try:
        result = extractor.extract_frames(input_path, dest_dir, pad_to=pad_to)
        # write logs to file
        try:
            with open(os.path.join(dest_dir, "extractor.log"), "w") as f:
                if result.logs:
                    f.write(result.logs)
        except Exception:
            pass
        # print JSON summary
        out = asdict(result)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        tb = traceback.format_exc()
        err_path = os.path.join(dest_dir, "extractor_error.log")
        try:
            with open(err_path, "w") as f:
                f.write(tb)
        except Exception:
            pass
        print(json.dumps({"error": str(e), "traceback": tb}))
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))

