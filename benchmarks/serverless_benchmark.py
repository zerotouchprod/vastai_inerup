#!/usr/bin/env python3
"""Offline benchmark reducer for RunPod Serverless result records.

This harness never calls RunPod, creates a pod, or starts a GPU workload. It consumes
one JSON object per line captured from the experimental handler and reports cold/warm
and phase-level metrics for an identical input chunk.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

REQUIRED_PHASES = (
    "queue_delay_s",
    "cold_boot_s",
    "model_load_s",
    "input_s",
    "setup_s",
    "rife_s",
    "realesrgan_s",
    "encode_s",
    "pipeline_s",
    "upload_s",
    "handler_total_s",
)


def load_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {number}: record must be an object")
        records.append(value)
    return records


def summarize(
    records: list[dict[str, Any]], rate_usd_per_hour: float = 0.0
) -> dict[str, Any]:
    if not records:
        raise ValueError("no benchmark records")
    key = (records[0].get("input_sha256"), records[0].get("input_duration_s"))
    if any((r.get("input_sha256"), r.get("input_duration_s")) != key for r in records):
        raise ValueError(
            "all records must use the same input_sha256 and input_duration_s"
        )
    valid = [r for r in records if r.get("ok") is True]
    if not valid:
        raise ValueError("no successful records")

    def avg(field: str) -> float | None:
        values = [
            float(r["timings"][field]) for r in valid if field in r.get("timings", {})
        ]
        return round(mean(values), 3) if values else None

    cold = [r for r in valid if not r.get("warm_start", False)]
    warm = [r for r in valid if r.get("warm_start", False)]
    result: dict[str, Any] = {
        "records": len(records),
        "successful": len(valid),
        "failed": len(records) - len(valid),
        "input_sha256": key[0],
        "input_duration_s": key[1],
        "cold_runs": len(cold),
        "warm_runs": len(warm),
        "encoder_counts": {
            encoder: sum(r.get("encoder_used") == encoder for r in valid)
            for encoder in sorted({str(r.get("encoder_used")) for r in valid})
        },
        "phase_mean_s": {field: avg(field) for field in REQUIRED_PHASES},
    }
    gpu_seconds = sum(float(r.get("timings", {}).get("pipeline_s", 0.0)) for r in valid)
    result["estimated_gpu_seconds"] = round(gpu_seconds, 3)
    result["estimated_cost_usd"] = round(gpu_seconds / 3600 * rate_usd_per_hour, 6)
    result["cold_mean_total_s"] = (
        round(mean(float(r["timings"]["handler_total_s"]) for r in cold), 3)
        if cold
        else None
    )
    result["warm_mean_total_s"] = (
        round(mean(float(r["timings"]["handler_total_s"]) for r in warm), 3)
        if warm
        else None
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "records", type=Path, help="JSONL handler results; no provider calls"
    )
    parser.add_argument("--rate-usd-per-hour", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = summarize(load_records(args.records), args.rate_usd_per_hour)
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
