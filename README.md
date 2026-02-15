# Extract Sharpest Frame

A lightweight Python CLI tool that extracts sharp frames from a video using `ffmpeg`'s `blurdetect` filter.

It analyzes the video frame-by-frame, splits frames into chunks, and picks the least blurry frame from each chunk.

## Features

- Automatic sharp frame selection with `blurdetect`
- Extracts one best frame per chunk (`--chunk-size`)
- `--blurdetect-only` mode for metadata workflow only
- Reuses existing blurdetect metadata in `--output-dir` when available
- Configurable analysis scale and blur block size
- JPEG quality and output naming control
- Minimal dependency setup (Python standard library + `ffmpeg`)

## Requirements

- Python 3.8+
- `ffmpeg` available in your system `PATH`

Check `ffmpeg`:

```bash
ffmpeg -version
```

## Installation

Clone this repository:

```bash
git clone https://github.com/Kotohibi/Extract_sharpest_frame.git
cd Extract_sharpest_frame
```

No extra Python packages are required.

## Usage

Basic example:

```bash
python extract_sharpest_frame.py --video /path/to/video.mp4
```

Example with custom output directory:

```bash
python extract_sharpest_frame.py \
  --video /path/to/video.mp4 \
  --output-dir ./frames
```

Example with fixed ffmpeg thread count:

```bash
python extract_sharpest_frame.py \
  --video /path/to/video.mp4 \
  --threads 4
```

Run blurdetect only (no frame extraction):

```bash
python extract_sharpest_frame.py \
  --video /path/to/video.mp4 \
  --output-dir ./frames \
  --blurdetect-only
```

If `./frames/_blurdetect_metadata.txt` already exists, the script skips blurdetect and uses that metadata for frame extraction.

Console messages:

- Existing metadata: `Using existing blurdetect metadata: ...`
- New metadata run: `Generating blurdetect metadata: ...`

## Command Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--video` | string | required | Input video file path |
| `--chunk-size` | int | `30` | Select 1 frame per N frames |
| `--scale-width` | int | `1920` | Width used for blur analysis |
| `--block-width` | int | `32` | `blurdetect` block width |
| `--block-height` | int | `32` | `blurdetect` block height |
| `--output-dir` | string | `sharp_frames` | Output directory |
| `--output-pattern` | string | `output_frame_%05d.jpg` | Output filename pattern (`ffmpeg` style) |
| `--qv` | int | `1` | JPEG quality for `-q:v` (lower is higher quality) |
| `--threads` | int | `0` | `ffmpeg` thread count (`0` = auto) |
| `--blurdetect-only` | flag | off | Metadata workflow only (no frame extraction) |

## How It Works

1. Reuses existing blurdetect metadata from `--output-dir` if available; otherwise runs `ffmpeg` with `blurdetect`.
2. Groups frames into chunks (`--chunk-size`).
3. Chooses the frame with the minimum blur score in each chunk.
4. Extracts selected frames to JPEG files.

## Notes

- Metadata is saved as `_blurdetect_metadata.txt` in `--output-dir` and can be reused in later runs.
- A smaller `--chunk-size` extracts more frames.
- If your source is very high resolution, lowering `--scale-width` can speed up analysis.

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file.
