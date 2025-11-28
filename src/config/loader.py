import json
from pathlib import Path
from typing import Union
from .schema import PipelineConfig

class ConfigLoader:
    """Load and validate pipeline configuration from JSON/YAML (simple JSON first).

    Usage:
        cfg = ConfigLoader.load('config.json')
        pc = cfg.load_config()
    """
    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)

    def read_raw(self) -> dict:
        text = self.path.read_text(encoding='utf-8')
        # only support JSON for initial scaffold
        return json.loads(text)

    def load_config(self) -> PipelineConfig:
        raw = self.read_raw()
        return PipelineConfig(**raw)

    @classmethod
    def load(cls, path: Union[str, Path]):
        return cls(path)


def load_config(path: Union[str, Path, None] = None) -> PipelineConfig:
    """Convenience loader used in tests/legacy code.

    If path is None, return a default PipelineConfig with source='default'.
    If path is provided, read JSON (allow empty dict) and return PipelineConfig with source set.
    """
    if path is None:
        # return defaults
        cfg = PipelineConfig(input_path='', output_path='', scale=2)
        # attach source attribute for tests
        setattr(cfg, 'source', 'default')
        return cfg

    p = Path(path)
    if not p.exists():
        # mimic previous behavior by returning defaults but record source
        cfg = PipelineConfig(input_path='', output_path='', scale=2)
        setattr(cfg, 'source', str(p))
        return cfg

    # read file content
    try:
        text = p.read_text(encoding='utf-8')
        if not text.strip():
            raw = {}
        else:
            raw = json.loads(text)
    except Exception:
        raw = {}

    # create config with defaults for missing fields
    input_path = raw.get('input_path', '')
    output_path = raw.get('output_path', '')
    scale = raw.get('scale', 2)
    batch_size = raw.get('batch_size', None)
    auto_tune = raw.get('auto_tune', False)
    cfg = PipelineConfig(input_path=input_path, output_path=output_path, scale=scale, batch_size=batch_size, auto_tune=auto_tune)
    setattr(cfg, 'source', str(p))
    return cfg
