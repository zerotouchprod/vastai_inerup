import json
from pathlib import Path
from src.config.loader import ConfigLoader
from src.config.schema import PipelineConfig

def test_loader(tmp_path):
    cfg = {
        "input_path": "input.mp4",
        "output_path": "out.mp4",
        "scale": 2
    }
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(cfg))
    loader = ConfigLoader(str(p))
    loaded = loader.load_config()
    assert isinstance(loaded, PipelineConfig)
    assert loaded.input_path == "input.mp4"
    assert loaded.scale == 2

