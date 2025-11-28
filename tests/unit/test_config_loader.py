import os
from src.config.loader import load_config
from src.config.schema import PipelineConfig


def test_load_config_default():
    cfg = load_config()
    assert isinstance(cfg, PipelineConfig)


def test_load_config_with_path(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text('{}')
    cfg = load_config(str(p))
    assert cfg.source == str(p)

