import threading
from pathlib import Path

import pytest


class FakeRife:
    pass


def test_rife_process_frames_stops_when_cancelled_before_pair(tmp_path):
    from src.infrastructure.processors.rife.native import RIFENative

    processor = RIFENative.__new__(RIFENative)
    processor.factor = 2.0
    processor.logger = type("Logger", (), {"info": lambda *a, **k: None})()
    processor._calculate_mids_per_pair = lambda: 1
    processor._load_model = lambda: None
    processor._load_frame_as_tensor = lambda path: path
    processor._interpolate_pair = lambda *args, **kwargs: [object()]
    processor._save_tensor_as_frame = lambda *args, **kwargs: None

    lost = threading.Event()
    lost.set()
    frames = [Path("a.png"), Path("b.png")]

    with pytest.raises(RuntimeError, match="cancelled"):
        processor.process_frames(frames, tmp_path, cancel_event=lost)


def test_rife_process_frames_reports_progress_and_checks_cancel(tmp_path):
    from src.infrastructure.processors.rife.native import RIFENative

    processor = RIFENative.__new__(RIFENative)
    processor.factor = 2.0
    processor.logger = type("Logger", (), {"info": lambda *a, **k: None})()
    processor._calculate_mids_per_pair = lambda: 1
    processor._load_model = lambda: None
    processor._load_frame_as_tensor = lambda path: path
    processor._interpolate_pair = lambda *args, **kwargs: [object()]
    processor._save_tensor_as_frame = lambda *args, **kwargs: None

    progress = []
    processor.process_frames(
        [Path("a.png"), Path("b.png")],
        tmp_path,
        progress_callback=lambda current, total: progress.append((current, total)),
        cancel_event=threading.Event(),
    )

    assert progress == [(1, 1)]
