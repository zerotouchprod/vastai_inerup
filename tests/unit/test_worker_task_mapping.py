from pathlib import Path

from src.worker.processors import task_to_job


def test_dual_model_task_parameters_are_applied_to_job():
    task = {
        "attempt_id": "pilot-attempt",
        "mode": "both",
        "params": {
            "scale": 2.0,
            "interp_factor": 2.0,
            "strategy": "interp-then-upscale",
        },
    }

    job = task_to_job(task, Path("/tmp/input.mp4"))

    assert job.mode == "both"
    assert job.scale == 2.0
    assert job.interp_factor == 2.0
    assert job.strategy == "interp-then-upscale"
    assert job.input_url == "/tmp/input.mp4"
