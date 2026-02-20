TODO: Short context and plan for a new AI
=======================================

1) Purpose of this file
-----------------------
This file is a short diary and TODO of changes made today in the repository, and an organized list of next steps / improvements. It can be handed to a new AI or developer for quick onboarding to the pipeline.

2) Plan (what I'll do in this file)
----------------------------------
- Describe the context of today's work.
- List key files and their roles.
- Record found issues and bugs/their fixes.
- Formulate a prioritized list of improvements (technical TODO).
- Provide commands for local/container runs and debugging.

3) Context — what was done today (summary)
------------------------------------------
- Fixed and stabilized `run_rife_pytorch.sh` — many small fixes around pipes, here-docs and correct use of `ffmpeg`.
- Added numeric pad calculation (compute pad_w/pad_h via `ffprobe`) instead of an ffmpeg filter expression (fixes filter parsing errors).
- Added detailed output/diagnostics after frame extraction (file list, hexdump of the first frame), and logging of ffmpeg output.
- Added a supported batch-runner: the script looks for `/workspace/project/batch_rife.py` and runs it to load the model once and generate middle frames (mids) into `$TMP_DIR/output`.
- Added a per-pair fallback: if the batch runner didn't work, `inference_img.py` is launched per-frame-pair (with timeout and logging).
- Added filelist concat for final mp4 assembly and a fallback to ffmpeg minterpolate if RIFE produced no outputs.
- Added diagnostic commands (nvidia-smi, torch.cuda info) and logging of batch_rife output.

4) Key logs / how to reproduce the issue / verification
------------------------------------------------------
- Typical pipeline run uses a command like:

```bash
python3 /workspace/project/pipeline.py --input /workspace/input.mp4 --output /workspace/output --mode interp --prefer auto --target-fps 70
```

- Or manually run the wrapper:

```bash
bash -x /apps/PycharmProjects/vastai_interup_ztp/run_rife_pytorch.sh /workspace/input.mp4 /workspace/output/output_interpolated.mp4 3 2>&1 | tee /workspace/run_rife_full.log
```

- After the run open TMP_DIR (the script prints TMP_DIR, for example /tmp/tmp.XYZ):

```bash
# replace TMP with the path printed by the script
TMP=/tmp/tmp.XYZ
ls -la "$TMP/input"
ls -la "$TMP/output"
sed -n '1,200p' "$TMP/batch_rife_run.log"
sed -n '1,200p' "$TMP/ff_extract.log"
```

5) Important notes and bugs found today
--------------------------------------
- FFmpeg filter parsing: expressions like `pad=if(mod(iw\,32),iw+(32-mod(iw\,32)),iw)` caused a "No such filter" error on some ffmpeg builds. Fix: compute pad values in shell (via ffprobe) and pass them as `pad=NUM:NUM`.
- Tensor size mismatch in RIFE: the model expects sizes divisible by a certain step (in RIFE v3.x there was a 64-multiple requirement in train_log). For robustness in `batch_rife.py` we pad inputs to the nearest multiple of 64; in the wrapper we handle extraction padding (multiple of 32) — this is the coordination between ffmpeg and the model.
- Issue: when the batch-runner didn't generate mids (error / missing script), the wrapper previously immediately fell back to ffmpeg minterpolate. Now the wrapper first attempts batch_rife, then per-pair inference, and only after that falls back to ffmpeg.

6) Repository structure (key files and folders)
-----------------------------------------------
Root structure (important items):
- `run_rife_pytorch.sh` — main wrapper for the interpolation step. Responsible for extracting frames, running batch-runner / per-pair inference, and assembling the final video.
- `pipeline.py` — main pipeline that coordinates steps (interpolate, upscale, upload, etc.). Calls `run_rife_pytorch.sh` for RIFE interpolation.
- `batch_rife.py` — lightweight batch runner (in repo root) — loads the RIFE model, processes frame pairs, writes intermediate mids to the `output` directory. CLI: `python3 batch_rife.py <in_dir> <out_dir> <factor>`.
- `external/RIFE/` — RIFE sources (model, `inference_img.py`, `train_log/`, etc.). Important files here:
  - `inference_img.py` — per-pair inference utility (from upstream RIFE).
  - `train_log/` — subfolder with model files (e.g., `flownet.pkl`, `RIFE_HDv3.py`, `IFNet_HDv3.py`).
- `external/Real-ESRGAN` — Real-ESRGAN implementation (for upscaling).
- `requirements.txt` — pip dependencies for container/venv.
- helpers: `pipeline.py`, `run_realesrgan_pytorch.sh`, `run_rife_pytorch.sh`, `scripts/*`.

6.1) Project entrypoint and monitor (important)
-----------------------------------------------
- Important: the canonical single entrypoint used in production runs is `run_with_config_batch_sync.py` (this is the top-level runner invoked by orchestration, not `pipeline.py` directly).
- `monitor.py` (also referenced as `monitor_instance.py` in some scripts) is the instance watchdog: it should detect successful upload to Backblaze B2 (or S3-compatible endpoint) and automatically stop the VM/container once the final file is uploaded to avoid extra charges.
- Current status: the automatic stop logic in `monitor.py` is not functioning reliably — the monitor does not consistently detect the completed B2 upload event and therefore does not trigger the instance shutdown. This needs to be fixed and tested.

10.1) Add monitor fix to TODO (high priority)
---------------------------------------------
- [ ] M1 — Fix automatic stop in `monitor.py`:
  - Ensure the monitor reliably detects successful upload completion to B2 (check upload manifest, returned ETag / file size, or use the same put result acknowledgement that the uploader uses).
  - If the uploader uses a two-step (upload temp -> move/rename) flow, the monitor must detect the final filename (or listen to an uploader success hook).
  - On detection, the monitor should perform a safe shutdown API call (or call the host agent) and log the event; it must also handle transient listing/latency issues (re-verify N times over a short window before stopping).
  - Add diagnostics: log B2 keys, upload events, the exact check used (size/sha1/etag), and a final "STOPPING INSTANCE" message with timestamp and reason.

10.2) Tests for monitor fix
---------------------------
- Add a small smoke test that simulates the uploader completing a file (e.g., write a marker file or call the same B2 API) and asserts that the monitor triggers shutdown logic (for tests: replace shutdown with writing a sentinel file or calling a dry-run endpoint).
- Add steps to run monitor locally in "dry-run" mode to validate detection logic:
  - `python3 monitor.py --dry-run --watch-dir /tmp/test_uploads --check-interval 5 --confirm 3`
  - Then simulate the uploader by copying the final file to `/tmp/test_uploads` and verify the monitor prints final detection and sentinel creation.

7) `batch_rife.py` interface (what it accepts/returns)
----------------------------------------------------
- Positional args: `in_dir` `out_dir` `factor`
- Environment: uses `REPO_DIR` (default `/workspace/project/external/RIFE`) to find `train_log` with the model.
- Logs to stdout: progress for each pair `Batch-runner: pair i/N done (M mids)` and diagnostics lines `DEBUG: input shapes after pad t0=(...)`.
- Output: files in `out_dir` with pattern `frame_%06d_mid[_XX].png`.

8) Quick instructions for local/container runs
---------------------------------------------
- Run the project (in a CUDA container on vast.ai):

```bash
# example pipeline invocation (as on vast.ai)
python3 /workspace/project/pipeline.py --input /workspace/input.mp4 --output /workspace/output --mode interp --prefer auto --target-fps 70
```

- Run only the RIFE wrapper (quick debug):

```bash
bash -x /apps/PycharmProjects/vastai_interup_ztp/run_rife_pytorch.sh /workspace/input.mp4 /workspace/output/output_interpolated.mp4 3 2>&1 | tee /workspace/run_rife_full.log
```

- Local testing of batch_rife (on extracted frames):

```bash
# prepare directories
mkdir -p /workspace/tmp_test/input /workspace/tmp_test/output
# put some frame_*.png files there
python3 /apps/PycharmProjects/vastai_interup_ztp/batch_rife.py /workspace/tmp_test/input /workspace/tmp_test/output 3
ls -la /workspace/tmp_test/output
```

9) Suggested improvements (priorities)
-------------------------------------
High (do in upcoming sprints):
- A1: Add CUDA / torch diagnostics to `batch_rife.py` logs (print `torch.cuda.is_available()`, `torch.cuda.device_count()`, `torch.cuda.get_device_name(0)`, memory_reserved/allocated). Currently the wrapper prints nvidia-smi and torch info, but it's useful to see this from the model loader context.
- A2: Add processing rate and ETA to `batch_rife.py`: every N pairs print `rate`, `pairs_done/total` and ETA. This gives helpful live progress.
- A3: Make `BATCH_TIMEOUT` configurable (via env var) instead of hardcoded 600s in the wrapper.

Medium (useful but more effort/risk):
- B1: Consider running batch_runner in the foreground (stdout/stderr directly into pipeline) to avoid background & wait-kill loops — simplifies debugging but slightly changes logging.
- B2: Improve padding coordination between ffmpeg and the model: consider supporting an `INFERENCE_PAD` (32 vs 64) and document model requirements.
- B3: Add unit/smoke tests for different inputs (2 frames, N frames, video without audio) and an integration test for the whole pipeline.

Low (optional):
- C1: Make filelist assembly support multiple templates and add `--filelist` option to the wrapper.
- C2: Rework `progress_collapse` into a small C/Python utility in repo for better performance.

10) Detailed TODO (concrete tasks)
---------------------------------
- [ ] A1 — Add CUDA / torch diagnostics to `batch_rife.py` logs (print `torch.cuda.is_available()`, `torch.cuda.device_count()`, `torch.cuda.get_device_name(0)`, memory_reserved/allocated).
- [ ] A2 — Add ETA & rate to `batch_rife.py` (measure wall time per N pairs, compute ETA).
- [ ] A3 — Replace hardcoded WAIT_SECS=600 in `run_rife_pytorch.sh` with `BATCH_TIMEOUT=${BATCH_TIMEOUT:-600}` and document it.
- [ ] B1 — Consider switching batch run to foreground (no & wait loop) for easier logs (configurable via env var RUN_BATCH_SYNC=1).
- [ ] B2 — Add config option `INFERENCE_PAD=64` or `INFERENCE_PAD=32` and align tests to avoid tensor size mismatches.
- [ ] B3 — Add smoke tests (GitHub Actions / local script) that run with 2‑3 frames and assert output exists.
- [ ] C1 — Add option `--filelist` to enable/disable filelist assembly.
- [ ] M1 — Fix automatic stop in `monitor.py`:
  - Ensure the monitor reliably detects successful upload completion to B2 (check upload manifest, returned ETag / file size, or use the same put result acknowledgement that uploader uses).
  - If the uploader uses a two-step (upload temp -> move/rename) flow, monitor must detect the final filename (or listen to uploader success hook).
  - On detection, monitor should perform a safe shutdown API call (or call host agent) and log the event; it must also handle transient listing/latency issues (re-verify N times over a short window before stopping).
  - Add diagnostics: log B2 keys, upload events, exact check used (size/sha1/etag), and a final "STOPPING INSTANCE" message with timestamp and reason.

11) Long explanation of flows (RIFE flow)
----------------------------------------
- The pipeline calls `run_rife_pytorch.sh` for the interpolation step.
- The wrapper extracts frames into `TMP_DIR/input` (pads to a multiple of 32 for ffmpeg compatibility and base operation). Then:
  - It attempts to run `batch_rife.py` (if available) — this is the main GPU path: the model is loaded on CUDA, pairs are processed and mids are written to `TMP_DIR/output`.
  - If `batch_rife` is absent or produced no outputs, the wrapper runs per-pair `inference_img.py` (from the RIFE repo) for each pair.
  - If per-pair also produces no results, the wrapper assembles video using ffmpeg minterpolate (CPU) as a last resort.
- After mids are obtained, the wrapper builds the final file using either filelist concat (preferred) or pattern `frame_%06d_mid.png` and reattaches audio if present.

12) Helpful notes for a new AI / developer
-----------------------------------------
- Logs are your friend: inspect `$TMP_DIR/ff_extract.log` and `$TMP_DIR/batch_rife_run.log`.
- A common cause of RIFE failures is mismatched spatial dimensions. If you see RuntimeError "Expected size 512 but got size 480" — adjust padding (in `batch_rife.py` there is an attempt to pad/crop but you might need to tweak the multiple).
- Verify PyTorch/CUDA versions and compatibility (logs show e.g., torch 2.x + cu121 — OK).
- For a quick smoke-test two frames are enough; the pipeline has disabled `inference_video.py` dependency (scikit-video) so we use pairwise inference.

13) What I expect from you / the next AI
--------------------------------------
- Adopt this TODO, implement A1 and A2 in `batch_rife.py` (small changes). I can submit a PR/patch myself after you say "apply A1/A2".
- After that, add a smoke-test to the repo and configure CI to automatically check the RIFE path on GPU.

14) Contacts / sources
---------------------
- Upstream RIFE repo (in `external/RIFE`) — read `README.md` and `inference_img.py` for API details.
- Current changes live in `run_rife_pytorch.sh` and `batch_rife.py`.

---

If you want, I can now: (a) automatically apply A1 (print use_cuda & memory) and A2 (ETA/rate) to `batch_rife.py`, (b) make WAIT_SECS configurable — say "apply A1/A2" and I'll make the edits and run a quick syntax check.
