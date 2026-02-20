"""
Unit tests for GenerationConfig.
Coverage target: config.py — defaults, validation, env override, kwargs.
"""

from __future__ import annotations


import pytest

from src.services.generation.config import GenerationConfig


class TestGenerationConfigDefaults:

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Strip all GEN_* env vars so Docker CMD doesn't bleed into default tests."""
        for key in ["GEN_ENABLE_SAFETY_CHECKER", "GEN_T2V_MODEL_ID", "GEN_I2V_MODEL_ID",
                    "GEN_DEFAULT_GUIDANCE_SCALE", "GEN_ENABLE_CPU_OFFLOAD",
                    "GEN_ENABLE_VAE_SLICING", "GEN_USE_BFLOAT16"]:
            monkeypatch.delenv(key, raising=False)

    def test_default_model_ids(self) -> None:
        cfg = GenerationConfig()
        assert cfg.T2V_MODEL_ID == "THUDM/CogVideoX-5b-I2V"
        assert cfg.I2V_MODEL_ID == "THUDM/CogVideoX-5b-I2V"
        assert "dreamshaper" in cfg.T2I_MODEL_ID.lower()

    def test_default_generation_params(self) -> None:
        cfg = GenerationConfig()
        assert cfg.DEFAULT_GUIDANCE_SCALE == 6.0
        assert cfg.DEFAULT_NUM_INFERENCE_STEPS == 50
        assert cfg.DEFAULT_NUM_FRAMES == 49
        assert cfg.DEFAULT_FPS == 8

    def test_default_optimizations(self) -> None:
        cfg = GenerationConfig()
        assert cfg.ENABLE_CPU_OFFLOAD is True
        assert cfg.ENABLE_VAE_SLICING is True
        assert cfg.USE_BFLOAT16 is True

    def test_default_safety_checker(self) -> None:
        cfg = GenerationConfig()
        assert cfg.ENABLE_SAFETY_CHECKER is True
        assert cfg.SAFETY_CHECKER_THRESHOLD == 0.5

    def test_default_limits(self) -> None:
        cfg = GenerationConfig()
        assert cfg.MAX_BATCH_SIZE == 100
        assert cfg.MAX_INFERENCE_STEPS == 200
        assert cfg.MAX_NUM_FRAMES == 96
        assert cfg.MAX_PROMPT_LENGTH == 1000


class TestGenerationConfigEnvOverride:

    def test_override_model_id_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEN_T2V_MODEL_ID", "custom/model")
        cfg = GenerationConfig()
        assert cfg.T2V_MODEL_ID == "custom/model"

    def test_override_guidance_scale_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEN_DEFAULT_GUIDANCE_SCALE", "7.5")
        cfg = GenerationConfig()
        assert cfg.DEFAULT_GUIDANCE_SCALE == 7.5

    def test_disable_safety_checker_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEN_ENABLE_SAFETY_CHECKER", "false")
        cfg = GenerationConfig()
        assert cfg.ENABLE_SAFETY_CHECKER is False


class TestGenerationConfigPaths:

    def test_temp_dir_path_creates_directory(self, tmp_path) -> None:
        cfg = GenerationConfig(TEMP_DIR=str(tmp_path / "gen_tmp"))
        path = cfg.temp_dir_path
        assert path.exists()
        assert path.is_dir()

    def test_hf_cache_path_creates_directory(self, tmp_path) -> None:
        cfg = GenerationConfig(HF_CACHE_DIR=str(tmp_path / "hf_cache"))
        path = cfg.hf_cache_path
        assert path.exists()
        assert path.is_dir()


class TestGenerationConfigOptimizationKwargs:

    def test_get_optimization_kwargs_returns_dict(self, tmp_path) -> None:
        cfg = GenerationConfig(HF_CACHE_DIR=str(tmp_path / "hf"))
        kwargs = cfg.get_optimization_kwargs()
        assert isinstance(kwargs, dict)

    def test_get_optimization_kwargs_has_cache_dir(self, tmp_path) -> None:
        cfg = GenerationConfig(HF_CACHE_DIR=str(tmp_path))
        kwargs = cfg.get_optimization_kwargs()
        assert "cache_dir" in kwargs

    def test_torch_dtype_without_torch(self, tmp_path) -> None:
        """torch is shimmed — property must not raise."""
        cfg = GenerationConfig(HF_CACHE_DIR=str(tmp_path))
        # Either returns a valid dtype or None — must not throw
        _ = cfg.torch_dtype
