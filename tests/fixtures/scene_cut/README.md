# Scene-cut regression fixtures

`mahoraga_64/` is 75 consecutive frames of the 3 s / 25 fps / 1080x1920 test clip used
in the 2026-11-20 prod validation of v0.1.129, downscaled to 64x64 grayscale. Only
these thumbnails are stored (not the source video).

Known hard/soft cuts (0-based source frame indices, matching ffmpeg `001.png` = frame 0):

- 24→25, 25→26: soft cuts (low SSIM, histogram L1 ≈ 0.07–0.08; missed by hist ≥ 0.35 alone)
- 26→27, 55→56: hard cuts (histogram L1 ≥ 0.35)
