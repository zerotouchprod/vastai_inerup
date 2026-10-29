# Encoding quality policy

## Verified size incident

A verified 197.555 s output was 3840x2160 H.264 at approximately 80.07 Mbps video bitrate. It contained one AAC stereo audio stream at approximately 194 kbps and no extra streams. The output duration and frame count were consistent; the final assembly did not add a second video stream or perform a second encode.

The production assembly command used `h264_nvenc -preset p6 -cq 19` without a bitrate ceiling. Constant-quality NVENC is intentionally allowed to spend more bits on complex 4K frames, so this combination can produce very large files. The observed result is therefore an encoding-policy issue, not an FPS/duration or duplicate-stream issue.

## Default policy

- H.264 NVENC remains the default production-compatible encoder.
- `preset=p6` remains unchanged.
- Default NVENC quality changes from `cq=19` to `cq=23`.
- A caller may override quality explicitly through `assemble_video(..., quality=...)`.
- No hard bitrate or file-size cap is introduced; complex scenes are not forcibly starved.
- HEVC NVENC accepts the same quality parameter when explicitly selected.

The quality value is clamped to FFmpeg's NVENC CQ range `0..51`.

## Offline control evidence

The original output was preserved. On a 5-second 4K segment, CPU-only controls (not production and not GPU inference) produced:

| Encoder | Quality | Segment size | Video bitrate | SSIM vs original output |
|---|---:|---:|---:|---:|
| libx264 ultrafast | CRF 19 | 56.2 MB | 89.25 Mbps | 0.8771 |
| libx264 ultrafast | CRF 23 | 34.0 MB | 54.06 Mbps | 0.8759 |
| libx265 ultrafast | CRF 24 | 8.8 MB | 14.05 Mbps | 0.8800 |

These CPU controls are directional evidence only: they are not NVENC performance or final visual-quality certification. The local host has no NVIDIA runtime (`nvidia-smi` unavailable), so no NVENC re-encode was fabricated or run.

For a 197.555-second source, linear size extrapolation is only a rough planning estimate; scene complexity and GOP structure can change the result materially.
