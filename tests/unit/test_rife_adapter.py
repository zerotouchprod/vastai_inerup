import os
from unittest import mock

from src.models.rife_adapter import RIFEAdapter, InterpResult


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').close()


@mock.patch('src.models.rife_adapter.run_cmd')
def test_run_batch_success(mock_run_cmd, tmp_path):
    # simulate batch script present and producing pngs
    batch_script = str(tmp_path / 'batch_rife.py')
    open(batch_script, 'w').close()
    in_dir = str(tmp_path / 'input')
    out_dir = str(tmp_path / 'output')
    os.makedirs(in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    # create a fake output png to be detected
    touch(os.path.join(out_dir, 'frame_000001_mid_01.png'))

    def run_cmd_side(cmd, timeout=None):
        return (0, 'batch ok', '')

    mock_run_cmd.side_effect = run_cmd_side
    adapter = RIFEAdapter(batch_script=batch_script)
    res = adapter.run_batch(in_dir, out_dir, factor=2, batch_cfg={})
    assert isinstance(res, InterpResult)
    assert res.success
    assert res.mids_count >= 1


@mock.patch('src.models.rife_adapter.run_cmd')
def test_run_batch_missing_script(mock_run_cmd, tmp_path):
    in_dir = str(tmp_path / 'in2')
    out_dir = str(tmp_path / 'out2')
    os.makedirs(in_dir, exist_ok=True)
    adapter = RIFEAdapter(batch_script=str(tmp_path / 'nope.py'))
    res = adapter.run_batch(in_dir, out_dir, factor=2, batch_cfg={})
    assert not res.success
    assert 'not found' in (res.logs or '') or 'missing' in (res.logs or '')


@mock.patch('src.models.rife_adapter.run_cmd')
def test_run_pairwise(mock_run_cmd, tmp_path):
    # create input frames
    in_dir = str(tmp_path / 'inp')
    out_dir = str(tmp_path / 'outp')
    os.makedirs(in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    for i in range(1, 5):
        touch(os.path.join(in_dir, f'frame_{i:06d}.png'))

    # simulate pair script present and producing output in ./output
    pair_script = str(tmp_path / 'pair.py')
    open(pair_script, 'w').close()

    # run_cmd: when called for pair, simulate creating ./output/img1.png
    def run_cmd_side(cmd, timeout=None):
        if 'pair.py' in ' '.join(cmd):
            os.makedirs('output', exist_ok=True)
            touch(os.path.join('output', 'img1.png'))
            return (0, 'ok', '')
        return (0, '', '')

    mock_run_cmd.side_effect = run_cmd_side
    adapter = RIFEAdapter(batch_script=str(tmp_path / 'unused'), pair_script=pair_script)
    res = adapter.run_pairwise(in_dir, out_dir, factor=2)
    assert isinstance(res, InterpResult)
    assert res.success
    assert res.mids_count >= 1

