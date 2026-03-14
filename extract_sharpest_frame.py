import argparse
import csv
import sys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from math import ceil
from pathlib import Path
from time import monotonic
from typing import Callable, Dict, List, Optional, Tuple

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
SPINNER_FRAMES = "|/-\\"
MULTIPROCESS_PROGRESS_INTERVAL = 0.2


class SharpestFrameError(Exception):
    pass


class SharpestFrameCancelled(SharpestFrameError):
    pass


class GuiTqdm(tqdm):
    def __init__(self, *args, logger: Logger = None, **kwargs) -> None:
        self.logger = logger
        self._last_displayed_message = ""
        super().__init__(*args, **kwargs)

    def update(self, n=1):
        displayed = super().update(n)
        if self.logger is not None:
            self.display()
        return displayed

    def display(self, msg=None, pos=None) -> None:
        if self.logger is None:
            super().display(msg=msg, pos=pos)
            return

        progress_message = msg if msg is not None else str(self)
        cleaned = progress_message.strip()
        if cleaned and cleaned != self._last_displayed_message:
            self._last_displayed_message = cleaned
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
        "bar_format": "{l_bar}{bar:20}{r_bar}",
    }

    if logger is None:
        return tqdm(**progress_kwargs)

    progress_kwargs["mininterval"] = 0
    progress_kwargs["miniters"] = 1
    progress_kwargs["ascii"] = False
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


def parse_jpeg_quality_value(value) -> int:
    if isinstance(value, int):
        quality = value
    else:
        normalized = str(value).strip()
        if normalized.endswith("%"):
            normalized = normalized[:-1].strip()

        try:
            quality = int(normalized)
        except ValueError as exc:
            raise SharpestFrameError("JPEG quality must be an integer percentage from 1 to 100.") from exc

    if quality < 1 or quality > 100:
        raise SharpestFrameError("JPEG quality must be between 1 and 100.")

    return quality


def build_analysis_ranges(total_frames: int, workers: int) -> List[Tuple[int, int]]:
    task_count = max(workers * 8, workers)
    range_size = max(1, ceil(total_frames / task_count))
    ranges: List[Tuple[int, int]] = []
    start_frame = 0

    while start_frame < total_frames:
        end_frame = min(total_frames, start_frame + range_size)
        ranges.append((start_frame, end_frame))
        start_frame = end_frame

    return ranges


def analyze_video_range(video_path: str, start_frame: int, end_frame: int, scale_width: int) -> List[Tuple[int, float]]:
    ensure_opencv_available()

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise SharpestFrameError(f"Failed to open video: {video_path}")

    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    results: List[Tuple[int, float]] = []
    frame_number = start_frame

    while frame_number < end_frame:
        ok, frame = capture.read()
        if not ok:
            break

        results.append((frame_number, compute_sharpness(frame, scale_width)))
        frame_number += 1

    capture.release()
    return results


def analyze_video_single_process(
    video_file: Path,
    metadata_path: Path,
    scale_width: int,
    total_frames: Optional[int],
    logger: Logger = None,
    should_cancel: CancelChecker = None,
) -> int:
    capture = cv2.VideoCapture(str(video_file))
    if not capture.isOpened():
        raise SharpestFrameError(f"Failed to open video: {video_file}")

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
    return frame_number


def analyze_video_multi_process(
    video_file: Path,
    metadata_path: Path,
    scale_width: int,
    total_frames: int,
    workers: int,
    logger: Logger = None,
    should_cancel: CancelChecker = None,
) -> int:
    ranges = build_analysis_ranges(total_frames, workers)
    completed_ranges: Dict[int, List[Tuple[int, float]]] = {}
    next_range_index = 0
    written_frames = 0
    spinner_index = 0
    last_progress_refresh = 0.0

    try:
        with metadata_path.open("w", newline="", encoding="utf-8") as metadata_file:
            writer = csv.writer(metadata_file)
            writer.writerow(["frame", "sharpness"])

            with create_progress(total=total_frames, desc="Analyze", logger=logger) as progress_bar:
                with ProcessPoolExecutor(max_workers=workers) as executor:
                    future_map = {
                        executor.submit(analyze_video_range, str(video_file), start_frame, end_frame, scale_width): index
                        for index, (start_frame, end_frame) in enumerate(ranges)
                    }

                    progress_bar.set_postfix_str(f"{SPINNER_FRAMES[spinner_index]} {len(future_map)} ranges")
                    progress_bar.display()
                    last_progress_refresh = monotonic()

                    while future_map:
                        raise_if_cancelled(should_cancel)

                        done_futures, _ = wait(future_map, timeout=0.1, return_when=FIRST_COMPLETED)
                        if not done_futures:
                            now = monotonic()
                            if now - last_progress_refresh >= MULTIPROCESS_PROGRESS_INTERVAL:
                                spinner_index = (spinner_index + 1) % len(SPINNER_FRAMES)
                                progress_bar.set_postfix_str(f"{SPINNER_FRAMES[spinner_index]} {len(future_map)} ranges")
                                progress_bar.display()
                                last_progress_refresh = now
                            continue

                        for future in done_futures:
                            range_index = future_map.pop(future)
                            segment_results = future.result()
                            completed_ranges[range_index] = segment_results
                            progress_bar.update(len(segment_results))

                        spinner_index = (spinner_index + 1) % len(SPINNER_FRAMES)
                        progress_bar.set_postfix_str(f"{SPINNER_FRAMES[spinner_index]} {len(future_map)} ranges")
                        progress_bar.display()
                        last_progress_refresh = monotonic()

                        while next_range_index in completed_ranges:
                            for frame_number, sharpness in completed_ranges.pop(next_range_index):
                                writer.writerow([frame_number, f"{sharpness:.10f}"])
                                written_frames += 1
                            next_range_index += 1

                    progress_bar.set_postfix_str("done")
                    progress_bar.display()
    except SharpestFrameCancelled:
        if metadata_path.exists():
            metadata_path.unlink()
        raise

    return written_frames


def analyze_video(
    video_file: Path,
    metadata_path: Path,
    scale_width: int,
    workers: int = 4,
    logger: Logger = None,
    should_cancel: CancelChecker = None,
) -> None:
    ensure_opencv_available()
    ensure_tqdm_available()
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    emit("[1/3] Analyzing sharpness...", logger)
    probe_capture = cv2.VideoCapture(str(video_file))
    if not probe_capture.isOpened():
        raise SharpestFrameError(f"Failed to open video: {video_file}")

    total_frames = get_frame_count(probe_capture)
    probe_capture.release()

    if workers <= 1 or total_frames is None or total_frames <= 1:
        frame_number = analyze_video_single_process(
            video_file=video_file,
            metadata_path=metadata_path,
            scale_width=scale_width,
            total_frames=total_frames,
            logger=logger,
            should_cancel=should_cancel,
        )
    else:
        frame_number = analyze_video_multi_process(
            video_file=video_file,
            metadata_path=metadata_path,
            scale_width=scale_width,
            total_frames=total_frames,
            workers=workers,
            logger=logger,
            should_cancel=should_cancel,
        )

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
    workers: int = 4,
    output_dir: str = "sharp_frames",
    output_pattern: str = "output_frame_%05d.jpg",
    jpeg_quality: int = 95,
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

    if workers <= 0:
        raise SharpestFrameError("--workers must be 1 or greater.")

    jpeg_quality = parse_jpeg_quality_value(jpeg_quality)

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
            workers=workers,
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
        jpeg_quality=jpeg_quality,
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
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Worker count for metadata extraction multiprocessing",
    )
    parser.add_argument("--output-dir", default="sharp_frames", help="Output directory")
    parser.add_argument(
        "--output-pattern",
        default="output_frame_%05d.jpg",
        help="Output filename pattern in printf format",
    )
    parser.add_argument(
        "--jpeg-quality",
        default="95",
        help="JPEG quality percentage from 1 to 100; values like 95 or 95%% are accepted",
    )
    parser.add_argument(
        "--analysis-only",
        action="store_true",
        help="Analyze frames and write metadata only without extracting images",
    )
    parser.add_argument(
        "--regenerate-metadata",
        dest="reuse_metadata",
        action="store_false",
        help="Ignore existing metadata and regenerate _sharpness_metadata.csv",
    )
    parser.add_argument(
        "--gui-log-output",
        action="store_true",
        help="Emit GUI-friendly progress lines instead of terminal-formatted tqdm output",
    )
    parser.set_defaults(reuse_metadata=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.gui_log_output and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    logger = (lambda message: print(message, flush=True)) if args.gui_log_output else None

    try:
        run_extraction(
            video=args.video,
            chunk_size=args.chunk_size,
            scale_width=args.scale_width,
            workers=args.workers,
            output_dir=args.output_dir,
            output_pattern=args.output_pattern,
            jpeg_quality=args.jpeg_quality,
            analysis_only=args.analysis_only,
            reuse_metadata=args.reuse_metadata,
            logger=logger,
        )
    except SharpestFrameError as exc:
        print(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()