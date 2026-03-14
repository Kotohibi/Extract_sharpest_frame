import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


def ensure_ffmpeg_exists() -> None:
    if shutil.which("ffmpeg") is None:
        print("Error: ffmpeg was not found. Please ensure it is available in PATH.")
        sys.exit(1)


def run_blurdetect(
    video_file: Path,
    metadata_path: Path,
    scale_width: int,
    block_width: int,
    block_height: int,
    threads: int,
) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_file_for_filter = metadata_path.name
    vf = (
        f"scale={scale_width}:-1,"
        f"blurdetect=block_width={block_width}:block_height={block_height},"
        f"metadata=print:file={metadata_file_for_filter}"
    )

    command = [
        "ffmpeg",
        "-hide_banner",
        "-threads",
        str(threads),
        "-i",
        str(video_file),
        "-vf",
        vf,
        "-an",
        "-f",
        "null",
        "-",
    ]

    print("[1/3] Running blurdetect...")
    result = subprocess.run(command, text=True, cwd=str(metadata_path.parent))
    if result.returncode != 0:
        print("Error: Failed to run blurdetect.")
        sys.exit(result.returncode)


def parse_best_frames(metadata_path: Path, chunk_size: int) -> List[int]:
    pattern_frame = re.compile(r"frame:(\d+)")
    pattern_blur = re.compile(r"lavfi\.blur=([0-9.]+)")

    frame_data: List[Tuple[int, float]] = []
    temp_frame_num = -1

    try:
        lines = metadata_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except FileNotFoundError:
        print(f"Error: Metadata file not found: {metadata_path}")
        sys.exit(1)

    for line in lines:
        line = line.strip()

        match_frame = pattern_frame.search(line)
        if match_frame:
            temp_frame_num = int(match_frame.group(1))
            continue

        match_blur = pattern_blur.search(line)
        if match_blur and temp_frame_num != -1:
            try:
                blur_val = float(match_blur.group(1))
                frame_data.append((temp_frame_num, blur_val))
            except ValueError:
                pass
            finally:
                temp_frame_num = -1

    if not frame_data:
        print("Error: No valid frame data was found in metadata.")
        sys.exit(1)

    best_frame_numbers: List[int] = []
    current_chunk: List[Tuple[int, float]] = []

    for data in frame_data:
        current_chunk.append(data)
        if len(current_chunk) == chunk_size:
            best = min(current_chunk, key=lambda x: x[1])
            best_frame_numbers.append(best[0])
            current_chunk = []

    if current_chunk:
        best = min(current_chunk, key=lambda x: x[1])
        best_frame_numbers.append(best[0])

    return best_frame_numbers


def extract_frames(
    video_file: Path,
    frame_numbers: List[int],
    output_dir: Path,
    output_pattern: str,
    jpeg_quality: int,
    threads: int,
) -> None:
    if not frame_numbers:
        print("No frames selected for extraction.")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_pattern

    select_expr = "+".join([f"eq(n,{frame})" for frame in frame_numbers])

    command = [
        "ffmpeg",
        "-hide_banner",
        "-threads",
        str(threads),
        "-i",
        str(video_file),
        "-vf",
        f"select='{select_expr}'",
        "-vsync",
        "0",
        "-q:v",
        str(jpeg_quality),
        str(output_path),
    ]

    print(f"[3/3] Extracting frames... ({len(frame_numbers)} frames)")
    result = subprocess.run(command, text=True)
    if result.returncode != 0:
        print("Error: Failed to extract frames.")
        sys.exit(result.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automatically extract sharp frames from a video using blurdetect."
    )
    parser.add_argument("--video", required=True, help="Input video file path")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=30,
        help="Select one frame per N frames (e.g., 30 at 30fps ~= once per second)",
    )
    parser.add_argument("--scale-width", type=int, default=1920, help="Width used for blurdetect")
    parser.add_argument("--block-width", type=int, default=32, help="blurdetect block width")
    parser.add_argument("--block-height", type=int, default=32, help="blurdetect block height")
    parser.add_argument("--output-dir", default="sharp_frames", help="Output directory")
    parser.add_argument(
        "--output-pattern",
        default="output_frame_%05d.jpg",
        help="Output filename pattern (ffmpeg format)",
    )
    parser.add_argument(
        "--qv",
        type=int,
        default=1,
        help="JPEG quality for -q:v (smaller means higher quality)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=0,
        help="ffmpeg thread count (0 = auto)",
    )
    parser.add_argument(
        "--blurdetect-only",
        action="store_true",
        help="Run blurdetect only and keep metadata without extracting frames",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    video_file = Path(args.video)
    if not video_file.exists():
        print(f"Error: Input video was not found: {video_file}")
        sys.exit(1)

    if args.chunk_size <= 0:
        print("Error: --chunk-size must be 1 or greater.")
        sys.exit(1)

    if args.threads < 0:
        print("Error: --threads must be 0 or greater.")
        sys.exit(1)

    ensure_ffmpeg_exists()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "_blurdetect_metadata.txt"

    metadata_exists = metadata_path.exists()

    if metadata_exists:
        print(f"Using existing blurdetect metadata: {metadata_path}")
    else:
        print(f"Generating blurdetect metadata: {metadata_path}")
        run_blurdetect(
            video_file=video_file,
            metadata_path=metadata_path,
            scale_width=args.scale_width,
            block_width=args.block_width,
            block_height=args.block_height,
            threads=args.threads,
        )

    if args.blurdetect_only:
        if metadata_exists:
            print("Done: Existing blurdetect metadata is available.")
        else:
            print("Done: blurdetect metadata was generated.")
        print(f"Metadata path: {metadata_path.resolve()}")
        return

    print("[2/3] Parsing metadata...")
    best_frames = parse_best_frames(metadata_path, args.chunk_size)

    extract_frames(
        video_file=video_file,
        frame_numbers=best_frames,
        output_dir=output_dir,
        output_pattern=args.output_pattern,
        jpeg_quality=args.qv,
        threads=args.threads,
    )

    print("Done: Sharp frames were extracted successfully.")
    print(f"Output directory: {Path(args.output_dir).resolve()}")


if __name__ == "__main__":
    main()
