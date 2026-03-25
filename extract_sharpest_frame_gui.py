import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from extract_sharpest_frame import PROGRESS_PREFIX


class ToolTip:
    def __init__(self, widget, text: str = "") -> None:
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def set_text(self, text: str) -> None:
        self.text = text

    def show_tip(self, event=None) -> None:
        if self.tip_window or not self.text:
            return

        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
            justify=tk.LEFT,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            font=("Segoe UI", 9),
        )
        label.pack(ipadx=4)

    def hide_tip(self, event=None) -> None:
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


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
        "output_format": "Output format",
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
        "close_dialog_title": "Process still running",
        "close_dialog_message": "A CLI process is still running. Force stop it and close the window?",
        "browse_video_title": "Select a video file",
        "browse_output_title": "Select an output folder",
        "lang_en": "English",
        "lang_ja": "Japanese",
        "tip_language": "Switch the UI language.",
        "tip_video": "Video file to analyze and extract sharp frames from.",
        "tip_output_dir": "Folder where metadata and extracted frames will be written.",
        "tip_chunk_size": "Select one sharpest frame from each chunk of this many frames.",
        "tip_scale_width": "Resize width used for sharpness analysis. Use 0 to analyze at original size.",
        "tip_workers": "Number of worker processes used during sharpness analysis.",
        "tip_output_pattern": "Printf-style output filename pattern. The extension follows Output format.",
        "tip_output_format": "Choose PNG or JPG for extracted frames.",
        "tip_jpeg_quality": "JPEG save quality. Used only when Output format is JPG.",
        "tip_analysis_only": "Only create sharpness metadata without saving extracted frames.",
        "tip_clear_log": "Clear the log output shown below.",
        "tip_stop": "Stop the running extraction process.",
        "tip_run": "Start analysis and extract the sharpest frame from each chunk.",
        "tip_log": "Shows progress, command output, and errors from the extractor.",
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
        "output_format": "出力形式",
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
        "close_dialog_title": "処理を実行中です",
        "close_dialog_message": "CLI の子プロセスがまだ実行中です。強制停止してウィンドウを閉じますか？",
        "browse_video_title": "動画ファイルを選択",
        "browse_output_title": "出力フォルダを選択",
        "lang_en": "英語",
        "lang_ja": "日本語",
        "tip_language": "GUI の表示言語を切り替えます。",
        "tip_video": "解析してシャープなフレームを切り出す動画ファイルです。",
        "tip_output_dir": "メタデータと切り出し画像の保存先フォルダです。",
        "tip_chunk_size": "このフレーム数ごとに最もシャープな1枚を選びます。",
        "tip_scale_width": "シャープネス解析時の縮小幅です。0 なら元解像度で解析します。",
        "tip_workers": "シャープネス解析に使うワーカープロセス数です。",
        "tip_output_pattern": "printf 形式の出力ファイル名です。拡張子は出力形式に合わせて変わります。",
        "tip_output_format": "切り出し画像の形式を PNG または JPG から選びます。",
        "tip_jpeg_quality": "JPEG 保存品質です。出力形式が JPG のときだけ使われます。",
        "tip_analysis_only": "画像は保存せず、シャープネスメタデータだけ作成します。",
        "tip_clear_log": "下のログ表示を消去します。",
        "tip_stop": "実行中の抽出処理を停止します。",
        "tip_run": "解析を開始し、各チャンクから最もシャープなフレームを抽出します。",
        "tip_log": "抽出処理の進捗、実行ログ、エラーを表示します。",
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
        self.output_pattern = tk.StringVar(value="output_frame_%05d.png")
        self.output_format = tk.StringVar(value="png")
        self.jpeg_quality = tk.StringVar(value="95")
        self.analysis_only = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar()
        self.log_queue = None
        self.worker_process: Optional[subprocess.Popen] = None
        self.log_thread: Optional[threading.Thread] = None
        self.stop_requested = False
        self.is_closing = False
        self.progress_line_active = False
        self.active_metadata_path: Optional[Path] = None
        self.active_metadata_may_be_partial = False
        self.tooltips: dict[str, ToolTip] = {}

        self._build_widgets()
        self._apply_translations()
        self.protocol("WM_DELETE_WINDOW", self._on_close_requested)
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
        self.workers_spinbox = ttk.Spinbox(root, from_=1, to=128, textvariable=self.workers, increment=1)
        self.workers_spinbox.grid(row=4, column=1, sticky="ew", pady=6)

        self.pattern_label = ttk.Label(root)
        self.pattern_label.grid(row=4, column=2, sticky="w", padx=(16, 8), pady=6)
        self.pattern_entry = ttk.Entry(root, textvariable=self.output_pattern)
        self.pattern_entry.grid(row=4, column=3, sticky="ew", pady=6)

        self.output_format_label = ttk.Label(root)
        self.output_format_label.grid(row=5, column=0, sticky="w", padx=(0, 8), pady=6)
        self.output_format_combo = ttk.Combobox(
            root,
            state="readonly",
            values=["png", "jpg"],
            textvariable=self.output_format,
        )
        self.output_format_combo.grid(row=5, column=1, sticky="ew", pady=6)
        self.output_format.trace_add("write", lambda *_args: self._sync_format_controls())

        self.jpeg_quality_label = ttk.Label(root)
        self.jpeg_quality_label.grid(row=5, column=2, sticky="w", padx=(16, 8), pady=6)
        self.jpeg_quality_entry = ttk.Entry(root, textvariable=self.jpeg_quality)
        self.jpeg_quality_entry.grid(row=5, column=3, sticky="ew", pady=6)

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

        self._create_tooltips()

    def _set_tooltip(self, name: str, widget, key: str) -> None:
        tooltip = self.tooltips.get(name)
        if tooltip is None:
            self.tooltips[name] = ToolTip(widget, self.t(key))
        else:
            tooltip.set_text(self.t(key))

    def _create_tooltips(self) -> None:
        self._set_tooltip("language_combo", self.language_combo, "tip_language")
        self._set_tooltip("video_entry", self.video_entry, "tip_video")
        self._set_tooltip("video_button", self.video_button, "tip_video")
        self._set_tooltip("output_entry", self.output_entry, "tip_output_dir")
        self._set_tooltip("output_button", self.output_button, "tip_output_dir")
        self._set_tooltip("chunk_entry", self.chunk_entry, "tip_chunk_size")
        self._set_tooltip("scale_entry", self.scale_entry, "tip_scale_width")
        self._set_tooltip("workers_spinbox", self.workers_spinbox, "tip_workers")
        self._set_tooltip("pattern_entry", self.pattern_entry, "tip_output_pattern")
        self._set_tooltip("output_format_combo", self.output_format_combo, "tip_output_format")
        self._set_tooltip("jpeg_quality_entry", self.jpeg_quality_entry, "tip_jpeg_quality")
        self._set_tooltip("analysis_checkbox", self.analysis_checkbox, "tip_analysis_only")
        self._set_tooltip("clear_button", self.clear_button, "tip_clear_log")
        self._set_tooltip("stop_button", self.stop_button, "tip_stop")
        self._set_tooltip("run_button", self.run_button, "tip_run")
        self._set_tooltip("log_text", self.log_text, "tip_log")

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
        self.output_format_label.configure(text=self.t("output_format"))
        self.jpeg_quality_label.configure(text=self.t("jpeg_quality"))
        self.analysis_checkbox.configure(text=self.t("analysis_only"))
        self.run_button.configure(text=self.t("run"))
        self.stop_button.configure(text=self.t("stop"))
        self.clear_button.configure(text=self.t("clear_log"))
        self.log_label.configure(text=self.t("log"))
        if not self._is_worker_running():
            self.status_text.set(self.t("ready"))
        self.language_combo.configure(values=["ja", "en"])
        self._create_tooltips()
        self._sync_format_controls()

    def _is_worker_running(self) -> bool:
        return self.worker_process is not None and self.worker_process.poll() is None

    def _get_app_base_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
        return Path(__file__).parent

    def _build_cli_command(
        self,
        video: str,
        output_dir: str,
        chunk_size: int,
        scale_width: int,
        workers: int,
        output_pattern: str,
        output_format: str,
        jpeg_quality: str,
        analysis_only: bool,
        reuse_metadata: bool,
    ) -> list[str]:
        base_dir = self._get_app_base_dir()
        if getattr(sys, "frozen", False):
            cli_exe = base_dir / "extract_sharpest_frame.exe"
            if not cli_exe.exists():
                raise FileNotFoundError(
                    f"Required extractor executable was not found: {cli_exe}"
                )
            command = [str(cli_exe)]
        else:
            command = [
                sys.executable,
                str(base_dir / "extract_sharpest_frame.py"),
            ]

        command.extend([
            "--gui-log-output",
            "--video",
            video,
            "--chunk-size",
            str(chunk_size),
            "--scale-width",
            str(scale_width),
            "--workers",
            str(workers),
            "--output-dir",
            output_dir,
            "--output-pattern",
            output_pattern,
            "--output-format",
            output_format,
            "--jpeg-quality",
            jpeg_quality,
        ])

        if analysis_only:
            command.append("--analysis-only")

        if not reuse_metadata:
            command.append("--regenerate-metadata")

        return command

    def _stream_process_output(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None

        for line in process.stdout:
            self.log_queue.put(("log", line.rstrip("\r\n")))

        process.stdout.close()
        return_code = process.wait()

        if self.stop_requested:
            self.log_queue.put(("cancelled", None))
        elif return_code == 0:
            self.log_queue.put(("done", None))
        else:
            self.log_queue.put(("error", f"CLI exited with code {return_code}."))

    def _force_kill_process_tree(self, process: subprocess.Popen) -> None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )

        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1.0)

    def _cleanup_partial_metadata(self) -> None:
        if self.active_metadata_may_be_partial and self.active_metadata_path and self.active_metadata_path.exists():
            self.active_metadata_path.unlink()

    def _stop_running_process(self, append_cancel_log: bool) -> None:
        if not self._is_worker_running():
            return

        self.stop_requested = True
        assert self.worker_process is not None
        self._force_kill_process_tree(self.worker_process)
        self._cleanup_partial_metadata()

        if append_cancel_log:
            self._append_log(self.t("cancelled"))

    def _on_close_requested(self) -> None:
        if self._is_worker_running():
            should_close = messagebox.askyesno(
                self.t("close_dialog_title"),
                self.t("close_dialog_message"),
            )
            if not should_close:
                return

            self.status_text.set(self.t("stopping"))
            self._append_log(self.t("stopping"))
            self._stop_running_process(append_cancel_log=False)

        self.is_closing = True
        self.destroy()

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

    def _sync_output_pattern_extension(self) -> None:
        pattern = self.output_pattern.get().strip()
        if not pattern:
            return

        output_format = self.output_format.get().strip().lower()
        if not output_format:
            return

        pattern_path = Path(pattern)
        target_suffix = f".{output_format}"

        if pattern_path.suffix:
            updated_pattern = str(pattern_path.with_suffix(target_suffix))
        else:
            updated_pattern = f"{pattern}{target_suffix}"

        if updated_pattern != pattern:
            self.output_pattern.set(updated_pattern)

    def _sync_format_controls(self) -> None:
        if self._is_worker_running():
            return

        self._sync_output_pattern_extension()
        is_jpg = self.output_format.get().lower() == "jpg"
        self.jpeg_quality_entry.configure(state="normal" if is_jpg else "disabled")

    def _set_running_state(self, running: bool) -> None:
        edit_state = "disabled" if running else "normal"
        self.run_button.configure(state=edit_state)
        self.video_button.configure(state=edit_state)
        self.output_button.configure(state=edit_state)
        self.language_combo.configure(state="disabled" if running else "readonly")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.status_text.set(self.t("running") if running else self.t("ready"))
        self.output_format_combo.configure(state="disabled" if running else "readonly")
        if not running:
            self._sync_format_controls()

    def _stop_run(self) -> None:
        if not self._is_worker_running():
            return

        self.status_text.set(self.t("stopping"))
        self._append_log(self.t("stopping"))
        self.stop_button.configure(state="disabled")
        self._stop_running_process(append_cancel_log=True)
        self.worker_process = None
        self.log_thread = None
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
            jpeg_quality = self._parse_jpeg_quality(self.jpeg_quality.get()) if self.output_format.get() == "jpg" else "95"
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
        self.log_queue = queue.Queue()
        self.stop_requested = False
        self._set_running_state(True)
        self._append_log(f"{self.t('running')} {Path(video)}")

        try:
            command = self._build_cli_command(
                video=video,
                output_dir=output_dir,
                chunk_size=chunk_size,
                scale_width=scale_width,
                workers=workers,
                output_pattern=self.output_pattern.get().strip(),
                output_format=self.output_format.get().strip(),
                jpeg_quality=jpeg_quality,
                analysis_only=self.analysis_only.get(),
                reuse_metadata=reuse_metadata,
            )
        except FileNotFoundError as exc:
            self._set_running_state(False)
            messagebox.showerror(self.t("failed"), str(exc))
            return

        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        startupinfo = None
        if sys.platform == "win32":
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)

        self.worker_process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        self.log_thread = threading.Thread(
            target=self._stream_process_output,
            args=(self.worker_process,),
            daemon=True,
        )
        self.log_thread.start()

    def _drain_log_queue(self) -> None:
        if self.is_closing:
            return

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
                self.log_thread = None
                self._set_running_state(False)
                messagebox.showinfo(self.t("title"), self.t("done"))
            elif kind == "cancelled":
                self._append_log(self.t("cancelled"))
                self.worker_process = None
                self.log_thread = None
                self._set_running_state(False)
            elif kind == "error":
                self._append_log(f"Error: {payload}")
                self.worker_process = None
                self.log_thread = None
                self._set_running_state(False)
                messagebox.showerror(self.t("failed"), payload)

        if self.worker_process and self.worker_process.poll() is not None and self.run_button["state"] == "disabled":
            self._set_running_state(False)
            self.worker_process = None
            self.log_thread = None

        self.after(100, self._drain_log_queue)


def main() -> None:
    app = SharpestFrameGui()
    app.mainloop()


if __name__ == "__main__":
    main()