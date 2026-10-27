import logging
import threading
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clear_upscaler_cache():
    from src.infrastructure.processors.realesrgan.native import clear_upscaler_cache

    clear_upscaler_cache()
    yield
    clear_upscaler_cache()


def _bare_processor(tile_size=512):
    from src.infrastructure.processors.realesrgan.native import RealESRGANNative

    processor = RealESRGANNative.__new__(RealESRGANNative)
    processor.tile_size = tile_size
    processor.scale = 2
    processor.half = False
    processor.batch_size = 1
    processor._explicit_batch_size = 1
    processor._use_fallback_scale = False
    processor.logger = logging.getLogger("upscale-test")
    processor._load_model = lambda: None
    processor._upsampler = None
    return processor


def test_upscale_process_frames_stops_when_cancelled_before_frame(tmp_path):
    processor = _bare_processor()
    lost = threading.Event()
    lost.set()

    with pytest.raises(RuntimeError, match="upscale cancelled"):
        processor.process_frames(
            [Path("a.png"), Path("b.png")],
            tmp_path,
            cancel_event=lost,
        )

    assert list(tmp_path.iterdir()) == []


def test_upscale_process_frames_reports_progress(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    processor = _bare_processor(tile_size=512)
    image = numpy.zeros((4, 4, 3), numpy.uint8)
    monkeypatch.setattr(cv2, "imread", lambda path, flag: image)

    class Upsampler:
        scale = 2

        def enhance(self, img, outscale=None):
            return img, None

    processor._upsampler = Upsampler()
    progress = []
    frames = [tmp_path / "in" / "frame_000001.png", tmp_path / "in" / "frame_000002.png"]

    processor.process_frames(
        frames,
        tmp_path / "out",
        progress_callback=lambda current, total: progress.append((current, total)),
        cancel_event=threading.Event(),
    )

    assert progress == [(1, 2), (2, 2)]


def test_cancel_between_frames_does_not_queue_the_next_write(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    processor = _bare_processor(tile_size=512)
    image = numpy.zeros((4, 4, 3), numpy.uint8)
    monkeypatch.setattr(cv2, "imread", lambda path, flag: image)
    writes = []

    def record_write(path, img, params=None):
        writes.append(Path(path).name)
        return True

    monkeypatch.setattr(cv2, "imwrite", record_write)
    lost = threading.Event()

    class Upsampler:
        scale = 2

        def enhance(self, img, outscale=None):
            return img, None

    processor._upsampler = Upsampler()

    def callback(current, total):
        if current == 1:
            lost.set()

    with pytest.raises(RuntimeError, match="upscale cancelled"):
        processor.process_frames(
            [Path("frame_000001.png"), Path("frame_000002.png")],
            tmp_path,
            progress_callback=callback,
            cancel_event=lost,
        )

    assert writes == ["frame_000001.png"]


def test_png_writer_uses_low_compression_and_waits(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    from src.infrastructure.processors.realesrgan.native import PngWriter

    started = threading.Event()
    release = threading.Event()
    seen = []

    def slow_write(path, image, params=None):
        seen.append((Path(path).name, params))
        started.set()
        assert release.wait(2)
        return True

    monkeypatch.setattr(cv2, "imwrite", slow_write)
    writer = PngWriter(workers=1, compression=1, max_pending=1)
    finished = threading.Event()

    def close_writer():
        writer.close()
        finished.set()

    writer.submit(tmp_path / "frame_000001.png", numpy.zeros((2, 2, 3), numpy.uint8))
    assert started.wait(2)
    closer = threading.Thread(target=close_writer)
    closer.start()
    assert not finished.wait(0.05)
    release.set()
    closer.join(2)
    assert finished.is_set()
    assert seen == [("frame_000001.png", [cv2.IMWRITE_PNG_COMPRESSION, 1])]


def test_orchestrator_upscale_passes_progress_and_cancel(tmp_path):
    from src.application.orchestrator import VideoProcessingOrchestrator
    from src.domain.models import Job, ProcessingResult

    captured = {}

    class Upscaler:
        def process(self, frames, output_dir, **options):
            captured["options"] = options
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "frame_000001.png").write_bytes(b"png")
            return ProcessingResult(success=True, output_path=output_dir, frames_processed=1)

    orchestrator = VideoProcessingOrchestrator.__new__(VideoProcessingOrchestrator)
    orchestrator._upscaler = Upscaler()
    lost = threading.Event()

    def callback(current, total):
        return None

    job = Job(
        job_id="job-1",
        input_url="file://in.mp4",
        mode="upscale",
        config={"cancel_event": lost, "progress_callback": callback},
    )

    orchestrator._process_frames(job, [Path("frame_000001.png")], tmp_path)

    assert captured["options"]["cancel_event"] is lost
    assert captured["options"]["progress_callback"] is callback


@pytest.mark.parametrize("strategy", ["interp-then-upscale", "upscale-then-interp"])
def test_orchestrator_both_mode_passes_progress_and_cancel(tmp_path, strategy):
    from src.application.orchestrator import VideoProcessingOrchestrator
    from src.domain.models import Job, ProcessingResult

    captured = {}

    class Stage:
        def __init__(self, name):
            self.name = name

        def process(self, frames, output_dir, **options):
            captured[self.name] = options
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "frame_000001.png").write_bytes(b"png")
            return ProcessingResult(success=True, output_path=output_dir, frames_processed=1)

    orchestrator = VideoProcessingOrchestrator.__new__(VideoProcessingOrchestrator)
    orchestrator._upscaler = Stage("upscale")
    orchestrator._interpolator = Stage("interp")
    orchestrator._logger = logging.getLogger("upscale-test")
    lost = threading.Event()

    def callback(current, total):
        return None

    job = Job(
        job_id="job-1",
        input_url="file://in.mp4",
        mode="both",
        strategy=strategy,
        config={"cancel_event": lost, "progress_callback": callback},
    )

    orchestrator._process_frames(job, [Path("frame_000001.png")], tmp_path)

    assert captured["upscale"]["cancel_event"] is lost
    assert captured["upscale"]["progress_callback"] is callback


def test_wrapper_passes_tile_progress_and_cancel(tmp_path, monkeypatch):
    from src.infrastructure.processors.realesrgan import native_wrapper

    seen = {}

    class Processor:
        def process_frames(self, frames, output_dir, progress_callback=None, cancel_event=None):
            seen["progress"] = progress_callback
            seen["cancel"] = cancel_event
            return [output_dir / "frame_000001.png"]

    def fake_get_upscaler(scale, half, device, tile_size, batch_size, logger=None):
        seen["tile_size"] = tile_size
        seen["scale"] = scale
        return Processor()

    monkeypatch.setattr(native_wrapper, "get_upscaler", fake_get_upscaler)
    wrapper = native_wrapper.RealESRGANNativeWrapper.__new__(native_wrapper.RealESRGANNativeWrapper)
    wrapper._logger = logging.getLogger("wrapper-test")
    wrapper._processor = None
    lost = threading.Event()

    def callback(current, total):
        return None

    wrapper._execute_processing(
        [tmp_path / "frame_000001.png"],
        tmp_path / "out",
        {
            "scale": 2,
            "progress_callback": callback,
            "cancel_event": lost,
        },
    )
    assert seen["tile_size"] is None
    assert seen["scale"] == 2
    assert seen["progress"] is callback
    assert seen["cancel"] is lost

    wrapper._execute_processing(
        [tmp_path / "frame_000001.png"],
        tmp_path / "out",
        {"scale": 2, "tile_size": 64},
    )
    assert seen["tile_size"] == 64


def test_batch_forward_runs_one_model_call():
    pytest.importorskip("torch")
    numpy = pytest.importorskip("numpy")
    from src.infrastructure.processors.realesrgan.native import batch_forward

    class Model:
        def __init__(self):
            self.shapes = []

        def __call__(self, tensor):
            self.shapes.append(tuple(tensor.shape))
            return tensor.repeat_interleave(2, dim=2).repeat_interleave(2, dim=3)

    model = Model()

    class Upsampler:
        half = False
        device = "cpu"
        scale = 2

        def __init__(self):
            self.model = model

    frames = [
        numpy.zeros((8, 8, 3), numpy.uint8),
        numpy.full((8, 8, 3), 255, numpy.uint8),
    ]
    outputs = batch_forward(Upsampler(), frames, 2)

    assert model.shapes == [(2, 3, 8, 8)]
    assert [out.shape for out in outputs] == [(16, 16, 3), (16, 16, 3)]
    assert outputs[0].dtype == numpy.uint8
    assert int(outputs[1][0, 0, 0]) == 255


def test_oom_switches_to_tile_512_and_cache_remembers_it(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    numpy = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from src.infrastructure.processors.realesrgan.native import (
        RealESRGANNative,
        get_upscaler,
    )

    loads = {"n": 0}
    enhances = {"n": 0}

    def load(self):
        if getattr(self, "_upsampler", None) is not None:
            return
        loads["n"] += 1

        class Upsampler:
            scale = 2
            tile_size = 0

            def enhance(self, img, outscale=None):
                enhances["n"] += 1
                return img, None

        self._upsampler = Upsampler()

    monkeypatch.setattr(RealESRGANNative, "_load_model", load)

    def explode(upsampler, frames, scale):
        raise torch.cuda.OutOfMemoryError("out of memory")

    monkeypatch.setattr(
        "src.infrastructure.processors.realesrgan.native.batch_forward",
        explode,
    )
    image = numpy.zeros((4, 4, 3), numpy.uint8)
    monkeypatch.setattr(cv2, "imread", lambda path, flag: image)

    processor = get_upscaler(2, True, "cpu", None, 1)
    assert processor.tile_size == 0
    frames = [Path("frame_000001.png"), Path("frame_000002.png")]
    output = processor.process_frames(frames, tmp_path)

    assert processor.tile_size == 512
    assert enhances["n"] == 2
    assert [path.name for path in output] == ["frame_000001.png", "frame_000002.png"]
    assert loads["n"] == 1
    assert (tmp_path / "frame_000001.png").exists()
    assert (tmp_path / "frame_000002.png").exists()

    again = get_upscaler(2, True, "cpu", None, 1)
    assert again is processor
    assert again.tile_size == 512
    assert loads["n"] == 1


def test_get_upscaler_loads_model_once(monkeypatch):
    from src.infrastructure.processors.realesrgan.native import (
        RealESRGANNative,
        get_upscaler,
    )

    loads = {"n": 0}

    def load(self):
        loads["n"] += 1
        self._upsampler = object()

    monkeypatch.setattr(RealESRGANNative, "_load_model", load)
    first = get_upscaler(2, True, "cpu", 0, 1)
    second = get_upscaler(2, True, "cpu", 0, 1)

    assert first is second
    assert loads["n"] == 1
