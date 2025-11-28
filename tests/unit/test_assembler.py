import os
import tempfile
from unittest import mock

from src.io.assembler import FrameAssembler, AssemblyResult


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').close()


@mock.patch('src.io.assembler.run_cmd')
def test_assemble_simple(mock_run_cmd, tmp_path):
    # Prepare 3 fake frames with same size
    frames = []
    for i in range(1, 4):
        p = tmp_path / f"frame_{i:06d}.png"
        touch(str(p))
        frames.append(str(p))

    # run_cmd behavior: ffprobe for each -> returns width,height,pix
    def run_cmd_side(cmd, timeout=None):
        s = ' '.join(cmd)
        if 'ffprobe' in cmd[0]:
            return (0, '640\n480\nrgb24\n', '')
        if 'ffmpeg' in cmd[0] and '-f concat' in s:
            # simulate creating out_path
            out = cmd[-1]
            touch(out)
            return (0, '', '')
        return (0, '', '')

    mock_run_cmd.side_effect = run_cmd_side
    assembler = FrameAssembler()
    outp = str(tmp_path / 'out.mp4')
    res = assembler.assemble(frames, None, outp, fps=24.0)
    assert isinstance(res, AssemblyResult)
    assert res.success
    assert res.output_path == outp


@mock.patch('src.io.assembler.run_cmd')
def test_assemble_normalize(mock_run_cmd, tmp_path):
    # Prepare frames with different sizes
    frames = []
    for i in range(1, 5):
        p = tmp_path / f"frame_{i:06d}.png"
        touch(str(p))
        frames.append(str(p))

    # run_cmd behavior: first few ffprobe return different sizes
    def run_cmd_side(cmd, timeout=None):
        s = ' '.join(cmd)
        if 'ffprobe' in cmd[0]:
            # simulate first file gives 800x600, second fails, third gives 800x600, etc
            path = cmd[-1]
            if 'frame_000001' in path:
                return (0, '800\n600\nyuv420p\n', '')
            if 'frame_000002' in path:
                return (1, '', 'err')
            return (0, '800\n600\nyuv420p\n', '')
        if 'ffmpeg' in cmd[0] and 'format=' in ' '.join(cmd):
            # normalization call: create normalized file
            for arg in cmd:
                if arg.endswith('.png') or arg.endswith('.jpg'):
                    outp = arg
            touch(outp)
            return (0, '', '')
        if 'ffmpeg' in cmd[0] and '-f concat' in ' '.join(cmd):
            # concat: create output
            outp = cmd[-1]
            touch(outp)
            return (0, '', '')
        return (0, '', '')

    mock_run_cmd.side_effect = run_cmd_side
    assembler = FrameAssembler()
    outp = str(tmp_path / 'out2.mp4')
    res = assembler.assemble(frames, None, outp, fps=30.0)
    assert isinstance(res, AssemblyResult)
    assert res.success
    assert res.output_path == outp

