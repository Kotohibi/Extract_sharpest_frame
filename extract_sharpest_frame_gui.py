import multiprocessing as mp
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from extract_sharpest_frame import PROGRESS_PREFIX, SharpestFrameCancelled, SharpestFrameError, run_extraction


def run_extraction_process(
    video: str,
    output_dir: str,
    chunk_size: int,
    scale_width: int,
    workers: int,
    output_pattern: str,
    jpeg_quality: str,
    analysis_only: bool,
    reuse_metadata: bool,
    result_queue,
) -> None:
    try:
        run_extraction(
            video=video,
            chunk_size=chunk_size,
            scale_width=scale_width,
            workers=workers,
            output_dir=output_dir,
            output_pattern=output_pattern,
            jpeg_quality=jpeg_quality,
            analysis_only=analysis_only,
            reuse_metadata=reuse_metadata,
            logger=lambda message: result_queue.put(("log", message)),
        )
        result_queue.put(("done", None))
    except SharpestFrameCancelled:
        result_queue.put(("cancelled", None))
    except (SharpestFrameError, Exception) as exc:
        result_queue.put(("error", str(exc)))


TRANSLATIONS = {
    "en": {
        "title": "Sharpest Frame Extractor",
        "language": "Language",
        "video": "Video file",
        "browse_video": "Browse...",
        "output_dir": "Output folder",
        "browse_output": "Browse...",
        "chunk_size": "Chunk size",
        "scale_width": "Scale width",
        "workers": "Workers",
        "output_pattern": "Output pattern",
        "jpeg_quality": "JPEG quality (%)",
        "analysis_only": "Analysis only",
        "run": "Run",
        "stop": "Stop",
        "running": "Running...",
        "stopping": "Stopping...",
        "ready": "Ready",
        "log": "Log",
        "clear_log": "Clear log",
        "select_video": "Select a video file.",
        "select_output": "Select an output folder.",
        "invalid_integer": "Please enter a valid integer for {field}.",
        "done": "Completed successfully.",
        "cancelled": "Processing was cancelled.",
        "failed": "Processing failed",
        "metadata_dialog_title": "Existing metadata found",
        "metadata_dialog_message": "Sharpness metadata already exists in the output folder. Use it for frame extraction?",
        "browse_video_title": "Select a video file",
        "browse_output_title": "Select an output folder",
        "lang_en": "English",
        "lang_ja": "Japanese",
    },
    "ja": {
        "title": "シャープフレーム抽出 GUI",
        "language": "言語",
        "video": "動画ファイル",
        "browse_video": "参照...",
        "output_dir": "出力フォルダ",
        "browse_output": "参照...",
        "chunk_size": "チャンクサイズ",
        "scale_width": "解析幅",
        "workers": "ワーカー数",
        "output_pattern": "出力ファイル名パターン",
        "jpeg_quality": "JPEG品質 (%)",
        "analysis_only": "解析のみ",
        "run": "実行",
        "stop": "停止",
        "running": "実行中...",
        "stopping": "停止中...",
        "ready": "準備完了",
        "log": "ログ",
        "clear_log": "ログを消去",
        "select_video": "動画ファイルを選択してください。",
        "select_output": "出力フォルダを選択してください。",
        "invalid_integer": "{field} には整数を入力してください。",
        "done": "処理が完了しました。",
        "cancelled": "処理を中断しました。",
        "failed": "処理に失敗しました",
        "metadata_dialog_title": "既存メタデータを検出",
        "metadata_dialog_message": "出力フォルダにシャープネスのメタデータがあります。これを使ってフレーム切り出しを行いますか？",
        "browse_video_title": "動画ファイルを選択",
        "browse_output_title": "出力フォルダを選択",
        "lang_en": "英語",
        "lang_ja": "日本語",
    },
}


class SharpestFrameGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.language = tk.StringVar(value="en")
        self.video_path = tk.StringVar()
        self.output_dir = tk.StringVar(value="sharp_frames")
        self.chunk_size = tk.StringVar(value="30")
        self.scale_width = tk.StringVar(value="1920")
        self.workers = tk.StringVar(value="4")
        self.output_pattern = tk.StringVar(value="output_frame_%05d.jpg")
        self.jpeg_quality = tk.StringVar(value="95")
        self.analysis_only = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar()
        self.log_queue = None
        self.worker_process: Optional[mp.Process] = None
        self.progress_line_active = False
        self.active_metadata_path: Optional[Path] = None
        self.active_metadata_may_be_partial = False

        self._build_widgets()
        self._apply_translations()
        self.after(100, self._drain_log_queue)

    def t(self, key: str) -> str:
        return TRANSLATIONS[self.language.get()][key]

    def _build_widgets(self) -> None:
        self.geometry("820x620")
        self.minsize(760, 540)

        root = ttk.Frame(self, padding=16)
        root.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        root.columnconfigure(3, weight=1)
        root.rowconfigure(6, weight=1)

        self.language_label = ttk.Label(root)
        self.language_label.grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 12))

        self.language_combo = ttk.Combobox(
            root,
            state="readonly",
            values=["ja", "en"],
            textvariable=self.language,
            width=12,
        )
        self.language_combo.grid(row=0, column=1, sticky="w", pady=(0, 12))
        self.language_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_translations())

        self.video_label = ttk.Label(root)
        self.video_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        self.video_entry = ttk.Entry(root, textvariable=self.video_path)
        self.video_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=6)
        self.video_button = ttk.Button(root, command=self._browse_video)
        self.video_button.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=6)

        self.output_label = ttk.Label(root)
        self.output_label.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=6)
        self.output_entry = ttk.Entry(root, textvariable=self.output_dir)
        self.output_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=6)
        self.output_button = ttk.Button(root, command=self._browse_output_dir)
        self.output_button.grid(row=2, column=3, sticky="ew", padx=(8, 0), pady=6)

        self.chunk_label = ttk.Label(root)
        self.chunk_label.grid(row=3, column=0, sticky="w", padx=(0, 8), pady=6)
        self.chunk_entry = ttk.Entry(root, textvariable=self.chunk_size)
        self.chunk_entry.grid(row=3, column=1, sticky="ew", pady=6)

        self.scale_label = ttk.Label(root)
        self.scale_label.grid(row=3, column=2, sticky="w", padx=(16, 8), pady=6)
        self.scale_entry = ttk.Entry(root, textvariable=self.scale_width)
        self.scale_entry.grid(row=3, column=3, sticky="ew", pady=6)

        self.workers_label = ttk.Label(root)
        self.workers_label.grid(row=4, column=0, sticky="w", padx=(0, 8), pady=6)
        self.workers_entry = ttk.Entry(root, textvariable=self.workers)
        self.workers_entry.grid(row=4, column=1, sticky="ew", pady=6)

        self.pattern_label = ttk.Label(root)
        self.pattern_label.grid(row=4, column=2, sticky="w", padx=(16, 8), pady=6)
        self.pattern_entry = ttk.Entry(root, textvariable=self.output_pattern)
        self.pattern_entry.grid(row=4, column=3, sticky="ew", pady=6)

        self.jpeg_quality_label = ttk.Label(root)
        self.jpeg_quality_label.grid(row=5, column=0, sticky="w", padx=(0, 8), pady=6)
        self.jpeg_quality_entry = ttk.Entry(root, textvariable=self.jpeg_quality)
        self.jpeg_quality_entry.grid(row=5, column=1, sticky="ew", pady=6)

        options_frame = ttk.Frame(root)
        options_frame.grid(row=6, column=0, columnspan=4, sticky="nsew", pady=(8, 0))
        options_frame.columnconfigure(0, weight=1)
        options_frame.rowconfigure(1, weight=1)

        self.analysis_checkbox = ttk.Checkbutton(options_frame, variable=self.analysis_only)
        self.analysis_checkbox.grid(row=0, column=0, sticky="w", pady=(0, 10))

        action_frame = ttk.Frame(options_frame)
        action_frame.grid(row=0, column=1, sticky="e", pady=(0, 10))
        self.clear_button = ttk.Button(action_frame, command=self._clear_log)
        self.clear_button.grid(row=0, column=0, padx=(0, 8))
        self.stop_button = ttk.Button(action_frame, command=self._stop_run)
        self.stop_button.grid(row=0, column=1, padx=(0, 8))
        self.stop_button.configure(state="disabled")
        self.run_button = ttk.Button(action_frame, command=self._start_run)
        self.run_button.grid(row=0, column=2)

        self.log_label = ttk.Label(options_frame)
        self.log_label.grid(row=1, column=0, columnspan=2, sticky="w")

        self.log_text = tk.Text(options_frame, wrap="word", height=18, state="disabled")
        self.log_text.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))

        scrollbar = ttk.Scrollbar(options_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=2, column=2, sticky="ns", pady=(6, 0))
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.status_label = ttk.Label(root, textvariable=self.status_text)
        self.status_label.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(12, 0))

    def _apply_translations(self) -> None:
        self.title(self.t("title"))
        self.language_label.configure(text=self.t("language"))
        self.video_label.configure(text=self.t("video"))
        self.video_button.configure(text=self.t("browse_video"))
        self.output_label.configure(text=self.t("output_dir"))
        self.output_button.configure(text=self.t("browse_output"))
        self.chunk_label.configure(text=self.t("chunk_size"))
        self.scale_label.configure(text=self.t("scale_width"))
        self.workers_label.configure(text=self.t("workers"))
        self.pattern_label.configure(text=self.t("output_pattern"))
        self.jpeg_quality_label.configure(text=self.t("jpeg_quality"))
        self.analysis_checkbox.configure(text=self.t("analysis_only"))
        self.run_button.configure(text=self.t("run"))
        self.stop_button.configure(text=self.t("stop"))
        self.clear_button.configure(text=self.t("clear_log"))
        self.log_label.configure(text=self.t("log"))
        if not self._is_worker_running():
            self.status_text.set(self.t("ready"))
        self.language_combo.configure(values=["ja", "en"])

    def _is_worker_running(self) -> bool:
        return self.worker_process is not None and self.worker_process.is_alive()

    def _browse_video(self) -> None:
        selected = filedialog.askopenfilename(title=self.t("browse_video_title"))
        if selected:
            self.video_path.set(selected)

    def _browse_output_dir(self) -> None:
        selected = filedialog.askdirectory(title=self.t("browse_output_title"))
        if selected:
            self.output_dir.set(selected)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.mark_unset("progress_start")
        self.log_text.mark_unset("progress_end")
        self.log_text.configure(state="disabled")
        self.progress_line_active = False

    def _append_log(self, message: str, replace: bool = False) -> None:
        self.log_text.configure(state="normal")

        if replace:
            if self.progress_line_active:
                self.log_text.delete("progress_start", "progress_end")
            else:
                self.log_text.mark_set("progress_start", "end-1c")
                self.log_text.mark_gravity("progress_start", tk.LEFT)

            self.log_text.insert("progress_start", message + "\n")
            self.log_text.mark_set("progress_end", "progress_start +1 lines")
            self.progress_line_active = True
        else:
            if self.progress_line_active:
                self.log_text.mark_unset("progress_start")
                self.log_text.mark_unset("progress_end")
                self.progress_line_active = False

            self.log_text.insert(tk.END, message + "\n")

        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _parse_int(self, value: str, field_key: str) -> int:
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(self.t("invalid_integer").format(field=self.t(field_key))) from exc

    def _parse_jpeg_quality(self, value: str) -> str:
        normalized = value.strip()
        if normalized.endswith("%"):
            normalized = normalized[:-1].strip()

        try:
            quality = int(normalized)
        except ValueError as exc:
            raise ValueError(self.t("invalid_integer").format(field=self.t("jpeg_quality"))) from exc

        if quality < 1 or quality > 100:
            raise ValueError(self.t("invalid_integer").format(field=self.t("jpeg_quality")))

        return str(quality)

    def _set_running_state(self, running: bool) -> None:
        edit_state = "disabled" if running else "normal"
        self.run_button.configure(state=edit_state)
        self.video_button.configure(state=edit_state)
        self.output_button.configure(state=edit_state)
        self.language_combo.configure(state="disabled" if running else "readonly")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.status_text.set(self.t("running") if running else self.t("ready"))

    def _stop_run(self) -> None:
        if not self._is_worker_running():
            return

        self.status_text.set(self.t("stopping"))
        self._append_log(self.t("stopping"))
        self.stop_button.configure(state="disabled")
        self.worker_process.terminate()
        self.worker_process.join(timeout=0.5)
        if self.worker_process.is_alive() and hasattr(self.worker_process, "kill"):
            self.worker_process.kill()
            self.worker_process.join(timeout=0.5)

        if self.active_metadata_may_be_partial and self.active_metadata_path and self.active_metadata_path.exists():
            self.active_metadata_path.unlink()

        self.worker_process = None
        self._append_log(self.t("cancelled"))
        self._set_running_state(False)

    def _start_run(self) -> None:
        if self._is_worker_running():
            return

        video = self.video_path.get().strip()
        output_dir = self.output_dir.get().strip()

        if not video:
            messagebox.showerror(self.t("failed"), self.t("select_video"))
            return

        if not output_dir:
            messagebox.showerror(self.t("failed"), self.t("select_output"))
            return

        try:
            chunk_size = self._parse_int(self.chunk_size.get().strip(), "chunk_size")
            scale_width = self._parse_int(self.scale_width.get().strip(), "scale_width")
            workers = self._parse_int(self.workers.get().strip(), "workers")
            jpeg_quality = self._parse_jpeg_quality(self.jpeg_quality.get())
        except ValueError as exc:
            messagebox.showerror(self.t("failed"), str(exc))
            return

        metadata_path = Path(output_dir) / "_sharpness_metadata.csv"
        reuse_metadata = True
        if metadata_path.exists():
            reuse_metadata = messagebox.askyesno(
                self.t("metadata_dialog_title"),
                self.t("metadata_dialog_message"),
            )

        self.active_metadata_path = metadata_path
        self.active_metadata_may_be_partial = (not metadata_path.exists()) or (metadata_path.exists() and not reuse_metadata)
        self.log_queue = mp.Queue()
        self._set_running_state(True)
        self._append_log(f"{self.t('running')} {Path(video)}")

        self.worker_process = mp.Process(
            target=run_extraction_process,
            args=(video, output_dir, chunk_size, scale_width, workers, self.output_pattern.get().strip(), jpeg_quality, self.analysis_only.get(), reuse_metadata),
            kwargs={"result_queue": self.log_queue},
        )
        self.worker_process.start()

    def _drain_log_queue(self) -> None:
        while self.log_queue is not None:
            try:
                kind, payload = self.log_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                if payload.startswith(PROGRESS_PREFIX):
                    self._append_log(payload[len(PROGRESS_PREFIX):], replace=True)
                else:
                    self._append_log(payload)
            elif kind == "done":
                self._append_log(self.t("done"))
                self.worker_process = None
                self._set_running_state(False)
                messagebox.showinfo(self.t("title"), self.t("done"))
            elif kind == "cancelled":
                self._append_log(self.t("cancelled"))
                self.worker_process = None
                self._set_running_state(False)
            elif kind == "error":
                self._append_log(f"Error: {payload}")
                self.worker_process = None
                self._set_running_state(False)
                messagebox.showerror(self.t("failed"), payload)

        if self.worker_process and not self.worker_process.is_alive() and self.run_button["state"] == "disabled":
            self._set_running_state(False)
            self.worker_process = None

        self.after(100, self._drain_log_queue)


def main() -> None:
    app = SharpestFrameGui()
    app.mainloop()


if __name__ == "__main__":
    mp.freeze_support()
    main()