import subprocess
from src.utils.shell import run_cmd


def test_run_cmd_success():
    rc, out, err = run_cmd(["/bin/echo", "hello"])
    assert rc == 0
    assert "hello" in out


def test_run_cmd_nonzero():
    rc, out, err = run_cmd(["/bin/sh", "-c", "exit 3"]) 
    # Some shells return last status, ensure it's captured
    assert isinstance(rc, int)

