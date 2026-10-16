"""Contract tests for the opt-in immutable-image CPU E2E runner."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "ops" / "runpod-pilot" / "docker-cpu-image-e2e.py"
POD_ARGS_PATH = REPO_ROOT / "ops" / "runpod-pilot" / "pod-args.json"


def load_runner():
    assert RUNNER_PATH.is_file(), "CPU image E2E runner is missing"
    spec = importlib.util.spec_from_file_location("runpod_cpu_image_e2e", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docker_command_uses_exact_pod_args_without_gpu_or_volume_mounts(tmp_path):
    runner = load_runner()
    pod_args = json.loads(POD_ARGS_PATH.read_text())
    env_file = tmp_path / "pod.env"

    image = "ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b"
    argv = runner.build_docker_argv(pod_args, image, env_file)

    image_index = argv.index(image)
    assert argv[image_index + 1 :] == pod_args["entrypoint"][1:] + pod_args["cmd"]
    assert argv[argv.index("--entrypoint") + 1] == pod_args["entrypoint"][0]
    assert argv[argv.index("--env-file") + 1] == str(env_file)
    assert "--add-host" in argv
    assert argv[argv.index("--add-host") + 1] == "195.234.126.233:host-gateway"
    assert "--gpus" not in argv
    assert "-v" not in argv and "--volume" not in argv
