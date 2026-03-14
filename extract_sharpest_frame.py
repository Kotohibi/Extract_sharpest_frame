import argparse
import csv
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


Logger = Optional[Callable[[str], None]]
CancelChecker = Optional[Callable[[], bool]]
PROGRESS_PREFIX = "[progress] "


class SharpestFrameError(Exception):
    pass


class SharpestFrameCancelled(SharpestFrameError):
    pass


class GuiTqdm(tqdm):
    def __init__(self, *args, logger: Logger = None, **kwargs) -> None:
        self.logger = logger
        super().__init__(*args, **kwargs)

    def display(self, msg=None, pos=None) -> None:
        if self.logger is None:
            super().display(msg=msg, pos=pos)
            return

        progress_message = msg if msg is not None else str(self)
        cleaned = progress_message.strip()
        if cleaned:
            emit_progress(cleaned, self.logger)


def emit(message: str, logger: Logger = None) -> None:
    if logger is None:
        print(message)
        return

    logger(message)


def emit_progress(message: str, logger: Logger = None) -> None:
    if logger is None:
        return

    logger(f"{PROGRESS_PREFIX}{message}")


def create_progress(total: Optional[int], desc: str, logger: Logger = None):
    progress_kwargs = {
        "total": total,
        "desc": desc,
        "unit": "frame",
        "dynamic_ncols": True,
        "leave": False,
    }

    if logger is None:
        return tqdm(**progress_kwargs)

    return GuiTqdm(logger=logger, **progress_kwargs)


def ensure_opencv_available() -> None:
    if cv2 is None:
        raise SharpestFrameError("opencv-python is required. Install it with: pip install -r requirements.txt")


def ensure_tqdm_available() -> None:
    if tqdm is None:
        raise SharpestFrameError("tqdm is required. Install it with: pip install -r requirements.txt")


def raise_if_cancelled(should_cancel: CancelChecker = None) -> None:
    if should_cancel is not None and should_cancel():
        raise SharpestFrameCancelled("Processing was cancelled.")


def get_frame_count(capture) -> Optional[int]:
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames > 0:
        return total_frames
    return None


def compute_sharpness(frame, scale_width: int) -> float:
    height, width = frame.shape[:2]

    if scale_width > 0 and width > scale_width:
        scale_ratio = scale_width / float(width)
        resized_height = max(1, int(height * scale_ratio))
        frame = cv2.resize(frame, (scale_width, resized_height), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def analyze_video(
    video_file: Path,
    metadata_path: Path,
    scale_width: int,
    logger: Logger = None,
    should_cancel: CancelChecker = None,
) -> None:
    ensure_opencv_available()
    ensure_tqdm_available()
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(video_file))
    if not capture.isOpened():
        raise SharpestFrameError(f"Failed to open video: {video_file}")

    emit("[1/3] Analyzing sharpness...", logger)
    total_frames = get_frame_count(capture)
    frame_number = 0
    try:
        with metadata_path.open("w", newline="", encoding="utf-8") as metadata_file:
            writer = csv.writer(metadata_file)
            writer.writerow(["frame", "sharpness"])

            with create_progress(total=total_frames, desc="Analyze", logger=logger) as progress_bar:
                while True:
                    raise_if_cancelled(should_cancel)

                    ok, frame = capture.read()
                    if not ok:
                        break

                    sharpness = compute_sharpness(frame, scale_width)
                    writer.writerow([frame_number, f"{sharpness:.10f}"])
                    frame_number += 1
                    progress_bar.update(1)
    except SharpestFrameCancelled:
        capture.release()
        if metadata_path.exists():
            metadata_path.unlink()
        raise

    capture.release()

    if frame_number == 0:
        raise SharpestFrameError("No frames could be read from the video.")


def parse_best_frames(
    metadata_path: Path,
    chunk_size: int,
    logger: Logger = None,
    should_cancel: CancelChecker = None,
) -> List[int]:
    ensure_tqdm_available()
    frame_data: List[Tuple[int, float]] = []

    try:
        with metadata_path.open("r", encoding="utf-8") as line_count_file:
            total_lines = max(0, sum(1 for _ in line_count_file) - 1)

        with metadata_path.open("r", newline="", encoding="utf-8") as metadata_file:
            reader = csv.DictReader(metadata_file)
            with create_progress(total=total_lines if total_lines > 0 else None, desc="Parse", logger=logger) as progress_bar:
                for row in reader:
                    raise_if_cancelled(should_cancel)

                    try:
                        frame_data.append((int(row["frame"]), float(row["sharpness"])))
                    except (KeyError, TypeError, ValueError):
                        pass
                    finally:
                        progress_bar.update(1)
    except FileNotFoundError as exc:
        raise SharpestFrameError(f"Metadata file not found: {metadata_path}") from exc

    if not frame_data:
        raise SharpestFrameError("No valid frame data was found in metadata.")

    best_frame_numbers: List[int] = []
    current_chunk: List[Tuple[int, float]] = []

    for data in frame_data:
        current_chunk.append(data)
        if len(current_chunk) == chunk_size:
            best = max(current_chunk, key=lambda item: item[1])
            best_frame_numbers.append(best[0])
            current_chunk = []

    if current_chunk:
        best = max(current_chunk, key=lambda item: item[1])
        best_frame_numbers.append(best[0])

    return best_frame_numbers


def ffmpeg_qv_to_jpeg_quality(qv: int) -> int:
    qv = max(1, min(31, qv))
    return max(5, 100 - ((qv - 1) * 3))


def format_output_filename(output_pattern: str, output_index: int) -> str:
    try:
        return output_pattern % output_index
    except (TypeError, ValueError):
        if "%d" not in output_pattern:
            return output_pattern
        raise SharpestFrameError(
            "--output-pattern must be a valid printf-style pattern such as output_frame_%05d.jpg"
        )


def save_frame(frame, output_file: Path, jpeg_quality: int) -> None:
    ensure_opencv_available()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    success = cv2.imwrite(str(output_file), frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not success:
        raise SharpestFrameError(f"Failed to write image: {output_file}")


def extract_frames(
    video_file: Path,
    frame_numbers: List[int],
    output_dir: Path,
    output_pattern: str,
    jpeg_quality: int,
    logger: Logger = None,
    should_cancel: CancelChecker = None,
) -> None:
    ensure_opencv_available()
    ensure_tqdm_available()

    if not frame_numbers:
        emit("No frames selected for extraction.", logger)
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    target_frame_numbers = set(frame_numbers)
    output_index = 1

    capture = cv2.VideoCapture(str(video_file))
    if not capture.isOpened():
        raise SharpestFrameError(f"Failed to open video: {video_file}")

    emit(f"[3/3] Extracting frames... ({len(frame_numbers)} frames)", logger)
    total_frames = get_frame_count(capture)

    frame_number = 0
    saved_count = 0
    with create_progress(total=total_frames, desc="Extract", logger=logger) as progress_bar:
        while True:
            raise_if_cancelled(should_cancel)

            ok, frame = capture.read()
            if not ok:
                break

            if frame_number in target_frame_numbers:
                output_name = format_output_filename(output_pattern, output_index)
                save_frame(frame, output_dir / output_name, jpeg_quality)
                output_index += 1
                saved_count += 1

                if saved_count == len(target_frame_numbers):
                    progress_bar.update(1)
                    break

            frame_number += 1
            progress_bar.update(1)

    capture.release()

    if saved_count != len(target_frame_numbers):
        raise SharpestFrameError(
            "Some selected frames could not be extracted. "
            f"Expected {len(target_frame_numbers)}, saved {saved_count}."
        )


def run_extraction(
    video: str,
    chunk_size: int = 30,
    scale_width: int = 1920,
    output_dir: str = "sharp_frames",
    output_pattern: str = "output_frame_%05d.jpg",
    qv: int = 1,
    analysis_only: bool = False,
    reuse_metadata: bool = True,
    logger: Logger = None,
    should_cancel: CancelChecker = None,
) -> Tuple[Path, List[int]]:
    ensure_opencv_available()
    ensure_tqdm_available()

    video_file = Path(video)
    if not video_file.exists():
        raise SharpestFrameError(f"Input video was not found: {video_file}")

    if chunk_size <= 0:
        raise SharpestFrameError("--chunk-size must be 1 or greater.")

    if scale_width < 0:
        raise SharpestFrameError("--scale-width must be 0 or greater.")

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir_path / "_sharpness_metadata.csv"

    raise_if_cancelled(should_cancel)

    if metadata_path.exists() and reuse_metadata:
        emit(f"Using existing sharpness metadata: {metadata_path}", logger)
    else:
        if metadata_path.exists() and not reuse_metadata:
            emit(f"Regenerating sharpness metadata: {metadata_path}", logger)
        else:
            emit(f"Generating sharpness metadata: {metadata_path}", logger)
        analyze_video(
            video_file=video_file,
            metadata_path=metadata_path,
            scale_width=scale_width,
            logger=logger,
            should_cancel=should_cancel,
        )

    if analysis_only:
        emit("Done: Sharpness metadata is available.", logger)
        emit(f"Metadata path: {metadata_path.resolve()}", logger)
        return metadata_path, []

    raise_if_cancelled(should_cancel)
    emit("[2/3] Parsing metadata...", logger)
    best_frames = parse_best_frames(metadata_path, chunk_size, logger=logger, should_cancel=should_cancel)

    extract_frames(
        video_file=video_file,
        frame_numbers=best_frames,
        output_dir=output_dir_path,
        output_pattern=output_pattern,
        jpeg_quality=ffmpeg_qv_to_jpeg_quality(qv),
        logger=logger,
        should_cancel=should_cancel,
    )

    emit("Done: Sharp frames were extracted successfully.", logger)
    emit(f"Output directory: {output_dir_path.resolve()}", logger)
    return metadata_path, best_frames


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract sharp frames from a video without the ffmpeg executable."
    )
    parser.add_argument("--video", required=True, help="Input video file path")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=30,
        help="Select one frame per N frames (e.g., 30 at 30fps ~= once per second)",
    )
    parser.add_argument(
        "--scale-width",
        type=int,
        default=1920,
        help="Width used for sharpness analysis; frames wider than this are resized",
    )
    parser.add_argument("--output-dir", default="sharp_frames", help="Output directory")
    parser.add_argument(
        "--output-pattern",
        default="output_frame_%05d.jpg",
        help="Output filename pattern in printf format",
    )
    parser.add_argument(
        "--qv",
        type=int,
        default=1,
        help="Approximate JPEG quality compatible with the original ffmpeg-style option (1-31)",
    )
    parser.add_argument(
        "--analysis-only",
        action="store_true",
        help="Analyze frames and write metadata only without extracting images",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        run_extraction(
            video=args.video,
            chunk_size=args.chunk_size,
            scale_width=args.scale_width,
            output_dir=args.output_dir,
            output_pattern=args.output_pattern,
            qv=args.qv,
            analysis_only=args.analysis_only,
            reuse_metadata=True,
        )
    except SharpestFrameError as exc:
        print(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()