"""
gui.py
------
The desktop UI. Built with CustomTkinter (falls back to plain Tkinter/ttk
automatically if CustomTkinter isn't installed, so the app still runs).

The actual conversion work happens in converter.py, on a background
thread, so the window never freezes. Progress updates cross the
thread boundary through a thread-safe queue that the main thread
drains on a Tkinter `after()` timer -- Tkinter widgets must only ever
be touched from the main thread.
"""

import os
import queue
import threading
import time
import traceback

try:
    import customtkinter as ctk
    _USING_CTK = True
except ImportError:  # graceful fallback if customtkinter isn't installed
    import tkinter as ctk_fallback
    from tkinter import ttk
    _USING_CTK = False

import tkinter as tk
from tkinter import filedialog, messagebox

from converter import export_video
from utils import (
    SUPPORTED_AUDIO_EXTS,
    SUPPORTED_IMAGE_EXTS,
    check_ffmpeg_installed,
    format_seconds,
    validate_audio_file,
    validate_image_file,
    validate_output_path,
)


APP_TITLE = "Audio to Video Converter (1080p)"
WINDOW_SIZE = "640x480"


class AudioToVideoApp:
    def __init__(self):
        if _USING_CTK:
            ctk.set_appearance_mode("System")
            ctk.set_default_color_theme("blue")
            self.root = ctk.CTk()
        else:
            self.root = ctk_fallback.Tk()

        self.root.title(APP_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.minsize(560, 440)

        self.audio_path = tk.StringVar()
        self.image_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.status_text = tk.StringVar(value="Ready.")
        self.eta_text = tk.StringVar(value="")

        self._progress_queue: "queue.Queue[tuple]" = queue.Queue()
        self._export_thread: threading.Thread | None = None
        self._cancel_requested = False
        self._export_start_time = 0.0

        self._build_ui()
        self._poll_queue()

        if not check_ffmpeg_installed():
            messagebox.showwarning(
                "FFmpeg not found",
                "FFmpeg (and ffprobe) could not be found on your PATH.\n\n"
                "Please install FFmpeg and make sure it is available from "
                "the command line before exporting a video.",
            )

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        pad = {"padx": 16, "pady": 8}

        Frame = ctk.CTkFrame if _USING_CTK else ttk.Frame
        Label = ctk.CTkLabel if _USING_CTK else ttk.Label
        Entry = ctk.CTkEntry if _USING_CTK else ttk.Entry
        Button = ctk.CTkButton if _USING_CTK else ttk.Button

        title = Label(self.root, text=APP_TITLE,
                       font=("Segoe UI", 18, "bold") if _USING_CTK else None)
        title.pack(pady=(18, 4))

        subtitle = Label(
            self.root,
            text="Turn an audio file + a background image into a 1920x1080 MP4.",
        )
        subtitle.pack(pady=(0, 10))

        form = Frame(self.root)
        form.pack(fill="x", **pad)

        self._add_file_row(form, "Audio file:", self.audio_path,
                            self._browse_audio, Label, Entry, Button)
        self._add_file_row(form, "Background image:", self.image_path,
                            self._browse_image, Label, Entry, Button)
        self._add_file_row(form, "Output (.mp4):", self.output_path,
                            self._browse_output, Label, Entry, Button)

        self.export_button = Button(
            self.root, text="Export Video", command=self._on_export_clicked
        )
        self.export_button.pack(pady=(14, 6))

        if _USING_CTK:
            self.progress_bar = ctk.CTkProgressBar(self.root, width=480)
            self.progress_bar.set(0)
        else:
            self.progress_bar = ttk.Progressbar(
                self.root, length=480, mode="determinate", maximum=1.0
            )
        self.progress_bar.pack(pady=(8, 4))

        status_row = Frame(self.root)
        status_row.pack(fill="x", padx=16)
        Label(status_row, textvariable=self.status_text).pack(side="left")
        Label(status_row, textvariable=self.eta_text).pack(side="right")

    def _add_file_row(self, parent, label_text, var, browse_cmd,
                       Label, Entry, Button):
        row = (ctk.CTkFrame if _USING_CTK else ttk.Frame)(parent)
        row.pack(fill="x", pady=6)

        Label(row, text=label_text, width=140 if _USING_CTK else None).pack(
            side="left"
        )
        entry = Entry(row, textvariable=var)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        Button(row, text="Browse...", width=90 if _USING_CTK else None,
               command=browse_cmd).pack(side="left")

    # ------------------------------------------------------------------ #
    # File dialogs
    # ------------------------------------------------------------------ #
    def _browse_audio(self):
        exts = " ".join(f"*{e}" for e in SUPPORTED_AUDIO_EXTS)
        path = filedialog.askopenfilename(
            title="Select audio file",
            filetypes=[("Audio files", exts), ("All files", "*.*")],
        )
        if path:
            self.audio_path.set(path)
            self._suggest_output_path()

    def _browse_image(self):
        exts = " ".join(f"*{e}" for e in SUPPORTED_IMAGE_EXTS)
        path = filedialog.askopenfilename(
            title="Select background image",
            filetypes=[("Image files", exts), ("All files", "*.*")],
        )
        if path:
            self.image_path.set(path)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Choose output location",
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4")],
        )
        if path:
            self.output_path.set(path)

    def _suggest_output_path(self):
        """Pre-fill an output path next to the audio file, if empty."""
        if self.output_path.get():
            return
        audio = self.audio_path.get()
        if not audio:
            return
        base, _ = os.path.splitext(audio)
        self.output_path.set(base + "_video.mp4")

    # ------------------------------------------------------------------ #
    # Export flow
    # ------------------------------------------------------------------ #
    def _on_export_clicked(self):
        if self._export_thread and self._export_thread.is_alive():
            return  # export already running

        audio = self.audio_path.get().strip()
        image = self.image_path.get().strip()
        output = self.output_path.get().strip()

        for err in (
            validate_audio_file(audio),
            validate_image_file(image),
            validate_output_path(output),
        ):
            if err:
                messagebox.showerror("Invalid input", err)
                return

        if not check_ffmpeg_installed():
            messagebox.showerror(
                "FFmpeg not found",
                "FFmpeg/ffprobe is not available on your PATH. "
                "Install FFmpeg and try again.",
            )
            return

        self._cancel_requested = False
        self._set_exporting_state(True)
        self._export_start_time = time.time()

        self._export_thread = threading.Thread(
            target=self._run_export, args=(image, audio, output), daemon=True
        )
        self._export_thread.start()

    def _run_export(self, image, audio, output):
        """Runs on the background thread. Never touches Tkinter widgets
        directly -- only pushes updates onto the thread-safe queue."""
        try:
            def on_progress(fraction: float):
                self._progress_queue.put(("progress", fraction))

            def is_cancelled():
                return self._cancel_requested

            export_video(
                image_path=image,
                audio_path=audio,
                output_path=output,
                progress_callback=on_progress,
                cancel_flag=is_cancelled,
            )
            self._progress_queue.put(("done", output))
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            traceback.print_exc()
            self._progress_queue.put(("error", str(exc)))

    # ------------------------------------------------------------------ #
    # Queue polling (runs on the main/UI thread)
    # ------------------------------------------------------------------ #
    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._progress_queue.get_nowait()
                if kind == "progress":
                    self._update_progress(payload)
                elif kind == "done":
                    self._on_export_done(payload)
                elif kind == "error":
                    self._on_export_error(payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._poll_queue)

    def _update_progress(self, fraction: float):
        if _USING_CTK:
            self.progress_bar.set(fraction)
        else:
            self.progress_bar["value"] = fraction

        elapsed = time.time() - self._export_start_time
        percent = int(fraction * 100)
        self.status_text.set(f"Exporting... {percent}%")

        if fraction > 0.02:
            estimated_total = elapsed / fraction
            remaining = max(0.0, estimated_total - elapsed)
            self.eta_text.set(f"ETA: {format_seconds(remaining)}")
        else:
            self.eta_text.set("ETA: calculating...")

    def _on_export_done(self, output_path: str):
        self._set_exporting_state(False)
        self._update_progress(1.0)
        self.status_text.set("Done.")
        self.eta_text.set("")
        messagebox.showinfo(
            "Export complete", f"Video exported successfully:\n{output_path}"
        )

    def _on_export_error(self, message: str):
        self._set_exporting_state(False)
        self.status_text.set("Failed.")
        self.eta_text.set("")
        if message != "cancelled":
            messagebox.showerror("Export failed", message)

    def _set_exporting_state(self, exporting: bool):
        state = "disabled" if exporting else "normal"
        self.export_button.configure(state=state)
        if not exporting:
            if _USING_CTK:
                self.progress_bar.set(0)
            else:
                self.progress_bar["value"] = 0
            self.status_text.set("Ready.")

    def run(self):
        self.root.mainloop()


def main():
    app = AudioToVideoApp()
    app.run()


if __name__ == "__main__":
    main()
