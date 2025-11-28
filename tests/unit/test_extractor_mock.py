import os
import json
import tempfile
from unittest import mock

import pytest

from src.io.extractor import FrameExtractor, ExtractResult


class DummyResult:
    def __init__(self, rc=0, out='640x480', err=''):
        self.rc = rc
        self.out = out
        self.err = err


def fake_run_cmd_probe(cmd):
    # probe
    if 'ffprobe' in cmd[0]:
        return (0, '640x480\n', '')
    # ffmpeg extract -> simulate creating files
    if 'image2' in cmd:
        # create a couple of fake pngs in the target path
        for p in cmd:
            if '%06d' in str(p):
                base = os.path.dirname(p)
                os.makedirs(base, exist_ok=True)
                open(os.path.join(base, 'frame_000001.png'), 'wb').close()
                open(os.path.join(base, 'frame_000002.png'), 'wb').close()
                break
        return (0, '', '')
    # audio
    if '-vn' in cmd:
        return (0, '', '')
    return (1, '', 'err')


@mock.patch('src.io.extractor.run_cmd', side_effect=fake_run_cmd_probe)
def test_extractor_creates_frames(mock_run_cmd, tmp_path):
    fe = FrameExtractor()
    dest = str(tmp_path / 'work')
    res = fe.extract_frames('/some/input.mp4', dest, pad_to=32)
    assert isinstance(res, ExtractResult)
    assert res.frames_count == 2
    assert res.width == 640
    assert res.height == 480
    # log contains probe info
    assert 'probe rc' in (res.logs or '')


@mock.patch('src.io.extractor.run_cmd')
def test_extractor_png_fallback_to_jpg(mock_run_cmd, tmp_path):
    # simulate probe success but png extraction fails (rc!=0), then jpg succeeds
    def side_effect(cmd):
        s = ' '.join(cmd)
        if 'ffprobe' in cmd[0]:
            return (0, '800x600\n', '')
        if 'vcodec png' in s:
            return (1, '', 'png error')
        if 'vcodec mjpeg' in s:
            # create jpgs
            for p in cmd:
                if '%06d' in str(p):
                    base = os.path.dirname(p)
                    os.makedirs(base, exist_ok=True)
                    open(os.path.join(base, 'frame_000001.jpg'), 'wb').close()
                    break
            return (0, '', '')
        if '-vn' in cmd:
            return (0, '', '')
        return (0, '', '')

    mock_run_cmd.side_effect = side_effect
    fe = FrameExtractor()
    dest = str(tmp_path / 'work2')
    res = fe.extract_frames('/some/input2.mp4', dest, pad_to=32)
    assert res.frames_count == 1
    assert res.width == 800
    assert res.height == 600

