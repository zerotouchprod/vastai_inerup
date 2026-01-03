# Test Fixtures

This directory contains test video fixtures for integration testing.

## Structure

- `videos/` - Sample videos for testing
  - `sample_with_audio.mp4` - Video with audio track
  - `sample_silent.mp4` - Video without audio
  - `sample_subtitles.mp4` - Video with hardcoded subtitles
  - `sample_watermark.mp4` - Video with watermark

## Downloading Test Videos

Test videos can be downloaded from Creative Commons sources or generated synthetically.

```bash
# Download sample videos
python tests/fixtures/download_samples.py
```

## Synthetic Video Generation

```bash
# Generate synthetic test videos
python tests/fixtures/generate_synthetic_videos.py
```

