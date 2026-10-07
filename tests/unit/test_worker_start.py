"""Behavioural tests for scripts/worker_start.sh using a stub interpreter (no GPU, no network)."""

import os
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "worker_start.sh"
TOKEN = "sekret-token-xyz"


def make_stub(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def env(tmp_path):
    counter = tmp_path / "calls"
    py = make_stub(tmp_path / "fakepython", f'echo "$@" >> "{counter}"\nexit 0\n')
    return {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "PYTHON": str(py),
        "AIVIDUP_API_URL": "https://aividup.test/api/worker",
        "AIVIDUP_WORKER_TOKEN": TOKEN,
        "AIVIDUP_WORKER_ID": "legacy-worker-id-is-ignored",
        "AIVIDUP_GPU_INSTANCE_ID": "gpu-123",
        "AIVIDUP_GPU_LEASE_ID": "lease-uuid",
        "AIVIDUP_BOOT_ID": "boot-uuid",
        "AIVIDUP_PROCESSOR": "ffmpeg",
        "AIVIDUP_RESTART_BACKOFF": "0",
        "_counter": str(counter),
        "_dir": str(tmp_path),
    }


def run(env, timeout=30, **over):
    e = {
        k: v
        for k, v in {**env, **over}.items()
        if v is not None and not k.startswith("_")
    }
    return subprocess.run(
        ["bash", str(SCRIPT)], env=e, capture_output=True, text=True, timeout=timeout
    )


def calls(env):
    p = Path(env["_counter"])
    return p.read_text().splitlines() if p.exists() else []


def test_requires_api_url_and_token_and_never_prints_token(env):
    r = run(env, AIVIDUP_API_URL=None)
    assert r.returncode == 2 and "AIVIDUP_API_URL" in r.stdout
    r = run(env, AIVIDUP_WORKER_TOKEN=None)
    assert r.returncode == 2 and "AIVIDUP_WORKER_TOKEN" in r.stdout
    assert (
        TOKEN
        not in run(env, AIVIDUP_DRY_RUN="1").stdout
        + run(env, AIVIDUP_DRY_RUN="1").stderr
    )


@pytest.mark.parametrize(
    "extra,expected",
    [
        ({"AIVIDUP_GPU_INSTANCE_ID": "explicit", "CONTAINER_ID": "999"}, "explicit"),
        ({"AIVIDUP_GPU_INSTANCE_ID": None, "CONTAINER_ID": "999"}, "999"),
        (
            {
                "AIVIDUP_GPU_INSTANCE_ID": None,
                "CONTAINER_ID": None,
                "VAST_CONTAINERLABEL": "C.12345",
            },
            "12345",
        ),
    ],
)
def test_provider_instance_id_resolution_order(env, extra, expected):
    r = run(env, AIVIDUP_DRY_RUN="1", **extra)
    assert r.returncode == 0 and f"--provider-instance-id {expected} " in r.stdout
    assert "--worker-id " in r.stdout and "legacy-worker-id-is-ignored" not in r.stdout


def test_no_provider_instance_id_is_a_config_error(env):
    r = run(
        env, AIVIDUP_GPU_INSTANCE_ID=None, CONTAINER_ID=None, VAST_CONTAINERLABEL=None
    )
    assert r.returncode == 2 and "provider instance id is unavailable" in r.stdout


@pytest.mark.parametrize(
    "over",
    [
        {"AIVIDUP_PROCESSOR": "gpu9000"},
        {"AIVIDUP_IDLE_EXIT_SECONDS": "soon"},
        {"AIVIDUP_API_URL": "ftp://x"},
    ],
)
def test_invalid_config_rejected(env, over):
    assert run(env, **over).returncode == 2


def test_dry_run_prints_the_command_without_token(env):
    r = run(env, AIVIDUP_DRY_RUN="1", AIVIDUP_IDLE_EXIT_SECONDS="120")
    assert (
        r.returncode == 0
        and "--processor ffmpeg" in r.stdout
        and "--idle-exit-seconds 120" in r.stdout
    )
    assert calls(env) == []  # nothing actually launched


def test_plain_http_to_remote_host_warns(env):
    r = run(env, AIVIDUP_API_URL="http://aividup.test/api/worker", AIVIDUP_DRY_RUN="1")
    assert "plain http" in r.stdout
    assert (
        "plain http"
        not in run(
            env, AIVIDUP_API_URL="http://127.0.0.1:8081/api/worker", AIVIDUP_DRY_RUN="1"
        ).stdout
    )


def test_idle_exit_is_a_clean_exit(env):
    r = run(env)
    assert r.returncode == 0 and "idle for" in r.stdout
    assert (
        len(calls(env)) == 1
        and "--api https://aividup.test/api/worker" in calls(env)[0]
    )
    assert (
        TOKEN not in calls(env)[0]
    )  # token travels in the environment only, never on the command line


def test_crash_is_not_restarted_inside_the_same_lease(env):
    state = Path(env["_dir"]) / "n"
    make_stub(
        Path(env["PYTHON"]),
        f'echo x >> "{env["_counter"]}"\n'
        f'n=$(cat "{state}" 2>/dev/null || echo 0); echo $((n+1)) > "{state}"\n[ "$n" -ge 2 ] && exit 0 || exit 1\n',
    )
    r = run(env)
    assert r.returncode == 4 and len(calls(env)) == 1
    assert "worker exited with code 1 (crash 1/0)" in r.stdout
    assert "exiting: too many crashes" in r.stdout


def test_nonzero_restart_override_is_rejected_before_worker_launch(env):
    make_stub(Path(env["PYTHON"]), f'echo x >> "{env["_counter"]}"\nexit 1\n')
    r = run(env, AIVIDUP_MAX_RESTARTS="3")
    assert r.returncode == 2 and "in-lease restarts are disabled" in r.stdout
    assert calls(env) == []


def test_self_destroy_only_when_enabled_and_uses_header_not_url(env):
    curl_log = Path(env["_dir"]) / "curl_calls"
    make_stub(Path(env["_dir"]) / "curl", f'echo "$@" >> "{curl_log}"\nexit 0\n')
    creds = {"CONTAINER_ID": "4242", "CONTAINER_API_KEY": "vast-key-abc"}

    run(env, **creds)  # flag off
    assert not curl_log.exists()

    r = run(env, AIVIDUP_SELF_DESTROY="1", **creds)
    assert r.returncode == 0 and "destroy requested" in r.stdout
    line = curl_log.read_text()
    assert "-X DELETE" in line and "/instances/4242/" in line
    assert (
        "Authorization: Bearer vast-key-abc" in line
        and "vast-key-abc" not in line.split("https://")[1]
    )
    assert "vast-key-abc" not in r.stdout


def test_self_destroy_needs_credentials(env):
    r = run(env, AIVIDUP_SELF_DESTROY="1")
    assert r.returncode == 0 and "skipping" in r.stdout


def test_config_error_also_triggers_self_destroy_dry_run(env):
    r = run(
        env,
        AIVIDUP_WORKER_TOKEN=None,
        AIVIDUP_SELF_DESTROY="1",
        AIVIDUP_DRY_RUN="1",
        CONTAINER_ID="7",
        CONTAINER_API_KEY="k",
    )
    assert r.returncode == 2 and "would destroy instance 7" in r.stdout


def test_sigterm_stops_without_self_destroy(env):
    curl_log = Path(env["_dir"]) / "curl_calls"
    make_stub(Path(env["_dir"]) / "curl", f'echo "$@" >> "{curl_log}"\n')
    make_stub(Path(env["PYTHON"]), "exec sleep 60\n")
    e = {
        k: v
        for k, v in {
            **env,
            "AIVIDUP_SELF_DESTROY": "1",
            "CONTAINER_ID": "1",
            "CONTAINER_API_KEY": "k",
        }.items()
        if not k.startswith("_")
    }
    p = subprocess.Popen(
        ["bash", str(SCRIPT)], env=e, stdout=subprocess.PIPE, text=True
    )
    time.sleep(1.5)
    p.send_signal(signal.SIGTERM)
    out, _ = p.communicate(timeout=20)
    assert p.returncode == 143 and "stopped by signal" in out and not curl_log.exists()


def test_max_lifetime_stops_a_running_worker(env):
    make_stub(Path(env["PYTHON"]), "exec sleep 60\n")
    t0 = time.monotonic()
    r = run(env, AIVIDUP_MAX_LIFETIME_SECONDS="2")
    assert (
        r.returncode == 0 and "max lifetime" in r.stdout and time.monotonic() - t0 < 15
    )


def test_orphaned_worker_is_killed_when_same_lease_restart_is_disabled(env):
    """If the supervised process dies hard, its leftovers must not keep running next to the replacement."""
    pidfile = Path(env["_dir"]) / "orphan.pid"
    n = Path(env["_dir"]) / "n"
    make_stub(
        Path(env["PYTHON"]),
        f'c=$(cat "{n}" 2>/dev/null || echo 0); echo $((c+1)) > "{n}"\n'
        f'if [ "$c" -eq 0 ]; then sleep 120 & echo $! > "{pidfile}"; kill -9 $PPID; wait; fi\nexit 0\n',
    )
    r = run(env)
    assert r.returncode == 4
    pid = int(pidfile.read_text())

    def alive() -> (
        bool
    ):  # a killed process may linger as a zombie until init reaps it; that is not "running"
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            return False
        return state != "Z"

    deadline = time.monotonic() + 3
    while alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not alive(), "orphaned worker process is still running"
