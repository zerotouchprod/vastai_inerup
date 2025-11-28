import pytest
from scripts.batch_helper import compute_batch_from_min_gpu_gb, parse_mem_list_mb, choose_batch_from_mem_list_mb, detect_oom_in_text


def test_compute_batch_from_min_gpu_gb():
    assert compute_batch_from_min_gpu_gb(6) == 1
    assert compute_batch_from_min_gpu_gb(12) == 2
    assert compute_batch_from_min_gpu_gb(15) == 2
    assert compute_batch_from_min_gpu_gb(16) == 4
    assert compute_batch_from_min_gpu_gb(23) == 4
    assert compute_batch_from_min_gpu_gb(24) == 8
    assert compute_batch_from_min_gpu_gb(32) == 16


def test_parse_mem_list_mb():
    assert parse_mem_list_mb(['16384', '8192 MiB', ' 4096\n']) == [16384, 8192, 4096]
    assert parse_mem_list_mb(['', 'no digits']) == []


def test_choose_batch_from_mem_list_mb():
    gb, batch = choose_batch_from_mem_list_mb([16384, 8192])
    assert gb == 8 and batch == 1  # min is 8192 -> 8GB -> batch 1
    gb, batch = choose_batch_from_mem_list_mb([32768, 32768])
    assert gb == 32 and batch == 16


def test_detect_oom_in_text():
    assert detect_oom_in_text('RuntimeError: CUDA out of memory')
    assert detect_oom_in_text('cuCtx failed with OOM')
    assert not detect_oom_in_text('all good')
    assert not detect_oom_in_text('')

