import os
from unittest import mock

from src.pipeline.orchestrator import PipelineOrchestrator, JobResult
from src.config.schema import PipelineConfig
from src.io.extractor import ExtractResult
from src.models.rife_adapter import InterpResult
from src.io.assembler import AssemblyResult
from src.io.uploader import UploadResult


def make_cfg():
    cfg = PipelineConfig()
    cfg.target_fps = 48
    cfg.b2_bucket = 'test-bucket'
    return cfg


@mock.patch('src.pipeline.orchestrator.FrameExtractor')

@mock.patch('src.pipeline.orchestrator.RIFEAdapter')
@mock.patch('src.pipeline.orchestrator.FrameAssembler')
@mock.patch('src.pipeline.orchestrator.IUploader')
def test_orchestrator_batch_success(mock_uploader_cls, mock_assembler_cls, mock_rife_cls, mock_extractor_cls, tmp_path):
    # setup mock extractor
    extractor = mock_extractor_cls.return_value
    extractor.extract_frames.return_value = ExtractResult(frames_count=10, width=640, height=480, pad_w=640, pad_h=480, audio_path=None, logs='ok')

    # setup batch success
    rife = mock_rife_cls.return_value
    rife.run_batch.return_value = InterpResult(mids_count=5, success=True, logs='batch ok')

    # assembler returns success
    assembler = mock_assembler_cls.return_value
    outp = str(tmp_path / 'out.mp4')
    assembler.assemble.return_value = AssemblyResult(success=True, output_path=outp, size_bytes=1234, logs='asm ok')

    # uploader
    uploader = mock_uploader_cls.return_value
    uploader.upload.return_value = UploadResult(success=True, key='k', url='u', attempts=1)

    orch = PipelineOrchestrator(make_cfg(), extractor, rife, assembler, uploader)
    res: JobResult = orch.run('/some/input.mp4', outp, work_dir=str(tmp_path / 'work'))
    assert res.success
    assert res.upload is not None


@mock.patch('src.pipeline.orchestrator.FrameExtractor')
@mock.patch('src.pipeline.orchestrator.RIFEAdapter')
@mock.patch('src.pipeline.orchestrator.FrameAssembler')
@mock.patch('src.pipeline.orchestrator.IUploader')
def test_orchestrator_batch_fail_pair_success(mock_uploader_cls, mock_assembler_cls, mock_rife_cls, mock_extractor_cls, tmp_path):
    extractor = mock_extractor_cls.return_value
    extractor.extract_frames.return_value = ExtractResult(frames_count=8, width=640, height=480, pad_w=640, pad_h=480, audio_path=None, logs='ok')

    rife = mock_rife_cls.return_value
    rife.run_batch.return_value = InterpResult(mids_count=0, success=False, logs='batch fail')
    rife.run_pairwise.return_value = InterpResult(mids_count=4, success=True, logs='pair ok')

    assembler = mock_assembler_cls.return_value
    outp = str(tmp_path / 'out2.mp4')
    assembler.assemble.return_value = AssemblyResult(success=True, output_path=outp, size_bytes=2222, logs='asm ok')

    uploader = mock_uploader_cls.return_value
    uploader.upload.return_value = UploadResult(success=True, key='k2', url='u2', attempts=1)

    orch = PipelineOrchestrator(make_cfg(), extractor, rife, assembler, uploader)
    res = orch.run('/some/input2.mp4', outp, work_dir=str(tmp_path / 'work2'))
    assert res.success
    assert res.upload.key == 'k2'


@mock.patch('src.pipeline.orchestrator.FrameExtractor')
@mock.patch('src.pipeline.orchestrator.RIFEAdapter')
@mock.patch('src.pipeline.orchestrator.FrameAssembler')
@mock.patch('src.pipeline.orchestrator.IUploader')
def test_orchestrator_both_fail(mock_uploader_cls, mock_assembler_cls, mock_rife_cls, mock_extractor_cls, tmp_path):
    extractor = mock_extractor_cls.return_value
    extractor.extract_frames.return_value = ExtractResult(frames_count=5, width=640, height=480, pad_w=640, pad_h=480, audio_path=None, logs='ok')

    rife = mock_rife_cls.return_value
    rife.run_batch.return_value = InterpResult(mids_count=0, success=False, logs='batch fail')
    rife.run_pairwise.return_value = InterpResult(mids_count=0, success=False, logs='pair fail')

    assembler = mock_assembler_cls.return_value

    uploader = mock_uploader_cls.return_value

    orch = PipelineOrchestrator(make_cfg(), extractor, rife, assembler, uploader)
    res = orch.run('/some/input3.mp4', str(tmp_path / 'out3.mp4'), work_dir=str(tmp_path / 'work3'))
    assert not res.success
    assert res.diagnostics_bundle is not None
    assert str(tmp_path / 'work3') in res.diagnostics_bundle

