from benchmarks.serverless_benchmark import summarize


def record(warm, total, pipeline, sha="a" * 64):
    return {
        "ok": True,
        "input_sha256": sha,
        "input_duration_s": 5.0,
        "warm_start": warm,
        "encoder_used": "libx264",
        "timings": {
            "input_s": 1.0,
            "setup_s": 2.0 if not warm else 0.1,
            "pipeline_s": pipeline,
            "upload_s": 0.5,
            "handler_total_s": total,
        },
    }


def test_summarize_separates_cold_warm_and_cost():
    result = summarize([record(False, 13, 10), record(True, 8, 6)], 36.0)

    assert result["cold_runs"] == 1
    assert result["warm_runs"] == 1
    assert result["phase_mean_s"]["pipeline_s"] == 8.0
    assert result["cold_phase_mean_s"]["pipeline_s"] == 10.0
    assert result["warm_phase_mean_s"]["pipeline_s"] == 6.0
    assert result["pipeline_seconds"] == 16.0
    assert result["billed_seconds"] == 21.0
    assert result["pipeline_only_cost_usd"] == 0.16
    assert result["estimated_cost_usd"] == 0.21


def test_summarize_rejects_mixed_inputs():
    try:
        summarize([record(False, 1, 1), record(True, 1, 1, sha="b" * 64)])
    except ValueError as exc:
        assert "same input" in str(exc)
    else:
        raise AssertionError("mixed inputs must be rejected")


def test_summarize_rejects_missing_or_invalid_input_identity():
    for bad in (
        record(False, 1, 1, sha="same") | {"input_sha256": None},
        record(False, 1, 1) | {"input_duration_s": 0},
    ):
        try:
            summarize([bad])
        except ValueError as exc:
            assert "input_" in str(exc)
        else:
            raise AssertionError("invalid input identity must be rejected")
