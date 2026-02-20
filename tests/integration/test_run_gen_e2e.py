"""
End-to-end tests for src/entrypoints/run_gen.py.

Chain under test:
  CLI args → parse_arguments() → GenJob → GenerationOrchestrator
  → MockEngine → real .mp4 on disk → JSON stdout → exit code

MockEngine injected via patch on GenerationOrchestrator._get_engine.
No GPU, no real model weights — real MP4 file IS created by the mock.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# shims installed at import time by mock_engines
from tests.mocks.mock_engines import (
    MockText2VideoEngine,
    MockImage2VideoEngine,
    MockUniversalEngine,
    _make_test_config,
)
from src.services.generation.config import GenerationConfig
from src.services.generation.models import GenerationMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_main(argv: list[str], engine_override: Any = None) -> tuple[int, dict]:
    """
    Run run_gen.main() with given argv.

    Patches:
    - sys.argv
    - GenerationOrchestrator._get_engine  → MockEngine
    - GenerationOrchestrator.__init__     → skips B2 init
    - builtins.print                      → captures JSON output only
      (logger writes to stderr via logging handlers — not captured here)

    Returns:
        (exit_code, parsed_stdout_json)
    """
    import builtins
    from src.entrypoints import run_gen
    from src.services.generation.orchestrator import GenerationOrchestrator

    printed_lines: list[str] = []

    def _capture_print(*args: Any, **kwargs: Any) -> None:
        printed_lines.append(" ".join(str(a) for a in args))

    def _fake_get_engine(self, mode: GenerationMode) -> Any:
        engine = engine_override or MockText2VideoEngine(config=self.config)
        engine.initialize()
        return engine

    with patch.object(sys, "argv", ["run_gen"] + argv), \
         patch.object(GenerationOrchestrator, "_get_engine", _fake_get_engine), \
         patch.object(GenerationOrchestrator, "__init__", _patched_orchestrator_init), \
         patch.object(builtins, "print", _capture_print):
        exit_code = run_gen.main()

    # find last parseable JSON line (print may be called once or with indent)
    full_output = "\n".join(printed_lines)
    # try to parse each printed call as JSON (last one wins)
    result: dict = {}
    for line in printed_lines:
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            pass

    if not result and full_output.strip():
        result = json.loads(full_output.strip())

    return exit_code, result


def _patched_orchestrator_init(self, config=None, b2_client=None):
    """Replacement __init__ that skips real B2 init."""
    from src.shared.logging import get_logger

    self.config = config or _make_test_config()
    self.logger = get_logger("test.orchestrator")
    self._t2v_engine = None
    self._i2v_engine = None
    self.b2_client = None
    self._current_job = None
    self._results = []


# ---------------------------------------------------------------------------
# T2V — single prompt, --no-upload
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRunGenT2VSinglePrompt:

    _JOB = json.dumps({
        "prompts": ["Anime girl walking in rain, cinematic"],
        "mode": "universal",
        "num_frames": 5,
        "fps": 8,
        "output_prefix": "e2e_test/",
    })

    def test_exit_code_zero(self, gen_config: GenerationConfig) -> None:
        engine = MockText2VideoEngine(config=gen_config)
        exit_code, _ = _run_main(["--job", self._JOB, "--no-upload"], engine)
        assert exit_code == 0

    def test_stdout_is_valid_json(self, gen_config: GenerationConfig) -> None:
        engine = MockText2VideoEngine(config=gen_config)
        _, data = _run_main(["--job", self._JOB, "--no-upload"], engine)
        assert isinstance(data, dict)

    def test_stdout_success_true(self, gen_config: GenerationConfig) -> None:
        engine = MockText2VideoEngine(config=gen_config)
        _, data = _run_main(["--job", self._JOB, "--no-upload"], engine)
        assert data.get("success") is True

    def test_stdout_results_count(self, gen_config: GenerationConfig) -> None:
        engine = MockText2VideoEngine(config=gen_config)
        _, data = _run_main(["--job", self._JOB, "--no-upload"], engine)
        assert data.get("total_prompts") == 1
        assert data.get("successful") == 1
        assert len(data.get("results", [])) == 1

    def test_result_has_output_key(self, gen_config: GenerationConfig) -> None:
        engine = MockText2VideoEngine(config=gen_config)
        _, data = _run_main(["--job", self._JOB, "--no-upload"], engine)
        key = data["results"][0]["output_key"]
        assert "e2e_test/" in key
        assert key.endswith(".mp4")

    def test_real_mp4_file_created(self, gen_config: GenerationConfig) -> None:
        """Core assertion: a real .mp4 file must exist on disk after the run."""
        engine = MockText2VideoEngine(config=gen_config)
        _, data = _run_main(["--job", self._JOB, "--no-upload"], engine)

        r = data["results"][0]
        # When no B2 upload, url = file:// pointing to local path
        assert r.get("url") is not None
        url: str = r["url"]
        assert url.startswith("file://")

        video_path = Path(url.replace("file://", ""))
        assert video_path.exists(), f"Expected MP4 at {video_path}"
        assert video_path.stat().st_size > 0, "MP4 file must not be empty"
        assert video_path.suffix == ".mp4"


# ---------------------------------------------------------------------------
# T2V — batch (3 prompts)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRunGenT2VBatch:

    _JOB = json.dumps({
        "prompts": ["Scene A", "Scene B", "Scene C"],
        "mode": "universal",
        "num_frames": 5,
        "output_prefix": "e2e_batch/",
    })

    def test_batch_all_succeed(self, gen_config: GenerationConfig) -> None:
        engine = MockText2VideoEngine(config=gen_config)
        exit_code, data = _run_main(["--job", self._JOB, "--no-upload"], engine)
        assert exit_code == 0
        assert data["successful"] == 3
        assert data["failed"] == 0

    def test_batch_three_mp4_files(self, gen_config: GenerationConfig) -> None:
        engine = MockText2VideoEngine(config=gen_config)
        _, data = _run_main(["--job", self._JOB, "--no-upload"], engine)

        for r in data["results"]:
            url: str = r["url"]
            assert url.startswith("file://")
            video_path = Path(url.replace("file://", ""))
            assert video_path.exists()
            assert video_path.stat().st_size > 0

    def test_batch_unique_output_keys(self, gen_config: GenerationConfig) -> None:
        engine = MockText2VideoEngine(config=gen_config)
        _, data = _run_main(["--job", self._JOB, "--no-upload"], engine)
        keys = [r["output_key"] for r in data["results"]]
        assert len(set(keys)) == 3


# ---------------------------------------------------------------------------
# I2V — single prompt
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRunGenI2V:

    _JOB = json.dumps({
        "mode": "image2video",
        "prompts": ["Make it dance"],
        "input_images": ["https://example.com/cat.jpg"],
        "num_frames": 5,
        "output_prefix": "e2e_i2v/",
    })

    def test_i2v_exit_code_zero(self, gen_config: GenerationConfig) -> None:
        engine = MockImage2VideoEngine(config=gen_config)
        exit_code, _ = _run_main(["--job", self._JOB, "--no-upload"], engine)
        assert exit_code == 0

    def test_i2v_mp4_created(self, gen_config: GenerationConfig) -> None:
        engine = MockImage2VideoEngine(config=gen_config)
        _, data = _run_main(["--job", self._JOB, "--no-upload"], engine)

        r = data["results"][0]
        video_path = Path(r["url"].replace("file://", ""))
        assert video_path.exists()
        assert video_path.stat().st_size > 0

    def test_i2v_result_mode_in_key(self, gen_config: GenerationConfig) -> None:
        engine = MockImage2VideoEngine(config=gen_config)
        _, data = _run_main(["--job", self._JOB, "--no-upload"], engine)
        key = data["results"][0]["output_key"]
        assert "i2v" in key


# ---------------------------------------------------------------------------
# UNIVERSAL — two-stage
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRunGenUniversal:

    _JOB = json.dumps({
        "mode": "universal",
        "prompts": ["Dragon flying over castle"],
        "num_frames": 5,
        "output_prefix": "e2e_universal/",
    })

    def test_universal_both_stages_called(self, gen_config: GenerationConfig) -> None:
        engine = MockUniversalEngine(config=gen_config)
        exit_code, data = _run_main(["--job", self._JOB, "--no-upload"], engine)

        assert exit_code == 0
        assert engine.t2i_call_count == 1
        assert engine.i2v_call_count == 1

    def test_universal_mp4_created(self, gen_config: GenerationConfig) -> None:
        engine = MockUniversalEngine(config=gen_config)
        _, data = _run_main(["--job", self._JOB, "--no-upload"], engine)

        video_path = Path(data["results"][0]["url"].replace("file://", ""))
        assert video_path.exists()
        assert video_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# Minimal output format
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_minimal_output_format(gen_config: GenerationConfig) -> None:
    import builtins
    from src.entrypoints import run_gen
    from src.services.generation.orchestrator import GenerationOrchestrator

    job = json.dumps({"prompts": ["test"], "mode": "universal", "num_frames": 5})
    engine = MockText2VideoEngine(config=gen_config)
    engine.initialize()

    printed: list[str] = []

    with patch.object(sys, "argv", ["run_gen", "--job", job, "--no-upload", "--output-format", "minimal"]), \
         patch.object(GenerationOrchestrator, "_get_engine", lambda self, m: engine), \
         patch.object(GenerationOrchestrator, "__init__", _patched_orchestrator_init), \
         patch.object(builtins, "print", lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
        run_gen.main()

    data = json.loads(printed[-1])
    assert "job_id" in data
    assert "successful" in data
    assert "failed" in data
    assert "results" not in data  # minimal format has no results list


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRunGenErrorHandling:

    def test_invalid_json_exits_1(self) -> None:
        import builtins
        from src.entrypoints import run_gen

        printed: list[str] = []
        with patch.object(sys, "argv", ["run_gen", "--job", "{invalid json"]), \
             patch.object(builtins, "print", lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            exit_code = run_gen.main()

        assert exit_code == 1
        data = json.loads(printed[-1])
        assert data["success"] is False

    def test_empty_prompts_exits_1(self) -> None:
        import builtins
        from src.entrypoints import run_gen
        from src.services.generation.orchestrator import GenerationOrchestrator

        job = json.dumps({"prompts": []})
        printed: list[str] = []

        with patch.object(sys, "argv", ["run_gen", "--job", job, "--no-upload"]), \
             patch.object(GenerationOrchestrator, "__init__", _patched_orchestrator_init), \
             patch.object(builtins, "print", lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            exit_code = run_gen.main()

        assert exit_code == 1

    def test_engine_failure_exits_1(self, gen_config: GenerationConfig) -> None:
        """If engine.generate raises, result must be failed and exit code 1."""
        import builtins
        from src.entrypoints import run_gen
        from src.services.generation.orchestrator import GenerationOrchestrator

        bad_engine = MagicMock()
        bad_engine.initialize.return_value = None
        bad_engine.generate.side_effect = RuntimeError("CUDA OOM")

        job = json.dumps({"prompts": ["test"], "mode": "universal", "num_frames": 5})
        printed: list[str] = []

        with patch.object(sys, "argv", ["run_gen", "--job", job, "--no-upload"]), \
             patch.object(GenerationOrchestrator, "_get_engine", lambda self, m: bad_engine), \
             patch.object(GenerationOrchestrator, "__init__", _patched_orchestrator_init), \
             patch.object(builtins, "print", lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            exit_code = run_gen.main()

        assert exit_code == 1
        data = json.loads(printed[-1])
        assert data["success"] is False
        assert data["failed"] == 1
