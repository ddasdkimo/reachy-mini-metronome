"""Practice recording module.

Records video from Reachy Mini's camera and audio from the system
default microphone, then merges them into an MP4 file using ffmpeg.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import sounddevice as sd
import soundfile as sf

from reachy_mini import ReachyMini

RECORDINGS_DIR = Path.home() / "reachy_mini_recordings"


class PracticeRecorder:
    """Records camera + microphone to MP4."""

    CAPTURE_FPS = 24
    STATE_IDLE = "idle"
    STATE_RECORDING = "recording"
    STATE_SAVING = "saving"

    def __init__(self, output_dir: str | Path = RECORDINGS_DIR,
                 frame_lock: threading.Lock | None = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Shared lock to protect concurrent get_frame() calls
        self.frame_lock = frame_lock or threading.Lock()

        self.state = self.STATE_IDLE
        self.elapsed = 0.0
        self.last_file: str | None = None

        self._recording = False
        self._thread: threading.Thread | None = None
        self._save_thread: threading.Thread | None = None
        self._writer: cv2.VideoWriter | None = None
        self._frame_count = 0
        self._reachy: ReachyMini | None = None
        self._start_time = 0.0
        self._temp_video = ""

        # Audio via sounddevice (system default mic)
        self._audio_stream: sd.InputStream | None = None
        self._audio_lock = threading.Lock()
        self._audio_chunks: deque[np.ndarray] = deque()
        self._sample_rate = 48000

        self._cleanup_temp_files()

    # ── public API ──

    def start(self, reachy_mini: ReachyMini) -> bool:
        if self.state != self.STATE_IDLE:
            return False

        with self.frame_lock:
            frame = reachy_mini.media.get_frame()
        if frame is None:
            return False

        self._reachy = reachy_mini
        h, w = frame.shape[:2]

        # Open video writer → temp AVI (MJPG, fast to write)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._temp_video = str(self.output_dir / f"_tmp_{ts}.avi")
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        self._writer = cv2.VideoWriter(self._temp_video, fourcc, self.CAPTURE_FPS, (w, h))
        self._writer.write(frame)
        self._frame_count = 1

        # Start audio capture from system default mic
        self._audio_chunks.clear()
        try:
            dev_info = sd.query_devices(sd.default.device[0], "input")
            self._sample_rate = int(dev_info["default_samplerate"])
            channels = min(dev_info["max_input_channels"], 2)
            self._audio_stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=channels,
                dtype="float32",
                callback=self._audio_callback,
            )
            self._audio_stream.start()
        except Exception:
            self._audio_stream = None

        self._recording = True
        self._start_time = time.time()
        self.elapsed = 0.0
        self.state = self.STATE_RECORDING

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self.state != self.STATE_RECORDING:
            return

        self.state = self.STATE_SAVING
        self._recording = False
        if self._thread:
            self._thread.join(timeout=10)

        if self._writer:
            self._writer.release()
            self._writer = None

        # Stop audio stream
        if self._audio_stream is not None:
            try:
                self._audio_stream.stop()
                self._audio_stream.close()
            except Exception:
                pass
            self._audio_stream = None

        duration = time.time() - self._start_time
        actual_fps = self._frame_count / duration if duration > 0 else self.CAPTURE_FPS

        # Snapshot data for background merge
        temp_video = self._temp_video
        with self._audio_lock:
            audio_chunks = list(self._audio_chunks)
            self._audio_chunks.clear()
        sample_rate = self._sample_rate

        self._save_thread = threading.Thread(
            target=self._background_save,
            args=(temp_video, audio_chunks, sample_rate, actual_fps),
            daemon=True,
        )
        self._save_thread.start()

    def _background_save(self, temp_video: str, audio_chunks: list[np.ndarray],
                         sample_rate: int, actual_fps: float) -> None:
        try:
            result = self._merge(temp_video, audio_chunks, sample_rate, actual_fps)
            self.last_file = result
        except Exception:
            self.last_file = None
        finally:
            self.state = self.STATE_IDLE

    def list_recordings(self) -> list[dict]:
        out = []
        for f in sorted(self.output_dir.iterdir()):
            if f.name.startswith("practice_") and f.is_file():
                out.append({
                    "filename": f.name,
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                })
        return out

    def get_file_path(self, filename: str) -> str | None:
        path = self.output_dir / filename
        if path.is_file() and filename.startswith("practice_"):
            return str(path)
        return None

    def delete_recording(self, filename: str) -> bool:
        path = self.output_dir / filename
        if path.is_file() and filename.startswith("practice_"):
            path.unlink()
            return True
        return False

    # ── private ──

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info: object, status: object) -> None:
        with self._audio_lock:
            self._audio_chunks.append(indata.copy())

    def _cleanup_temp_files(self) -> None:
        """Remove orphaned temp files from a previous crashed session."""
        for f in self.output_dir.iterdir():
            if f.name.startswith("_tmp_") and f.is_file():
                try:
                    f.unlink()
                except OSError:
                    pass

    def _capture_loop(self) -> None:
        interval = 1.0 / self.CAPTURE_FPS

        while self._recording:
            t0 = time.time()
            self.elapsed = t0 - self._start_time

            try:
                with self.frame_lock:
                    frame = self._reachy.media.get_frame()
                if frame is not None and self._writer:
                    self._writer.write(frame)
                    self._frame_count += 1
            except Exception:
                pass

            dt = interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)

    def _merge(self, temp_video: str, audio_chunks: list[np.ndarray],
               sample_rate: int, actual_fps: float) -> str | None:
        ts = os.path.basename(temp_video).replace("_tmp_", "").replace(".avi", "")

        # Write audio WAV
        temp_audio: str | None = None
        if audio_chunks:
            audio_data = np.concatenate(audio_chunks, axis=0)
            temp_audio = str(self.output_dir / f"_tmp_{ts}.wav")
            sf.write(temp_audio, audio_data, sample_rate)

        output = str(self.output_dir / f"practice_{ts}.mp4")

        if not shutil.which("ffmpeg"):
            # No ffmpeg — keep raw AVI
            fallback = output.replace(".mp4", ".avi")
            os.rename(temp_video, fallback)
            if temp_audio:
                os.remove(temp_audio)
            return os.path.basename(fallback)

        try:
            cmd = ["ffmpeg", "-y", "-r", str(actual_fps), "-i", temp_video]
            if temp_audio:
                cmd += ["-i", temp_audio]
            cmd += [
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                "-movflags", "+faststart",
                output,
            ]
            if not temp_audio:
                # replace audio flags with -an
                cmd = ["ffmpeg", "-y", "-r", str(actual_fps), "-i", temp_video,
                       "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                       "-an", "-movflags", "+faststart", output]

            subprocess.run(cmd, capture_output=True, timeout=120, check=True)
            os.remove(temp_video)
            if temp_audio:
                os.remove(temp_audio)
            return os.path.basename(output)
        except Exception:
            fallback = output.replace(".mp4", ".avi")
            if os.path.exists(temp_video):
                os.rename(temp_video, fallback)
            if temp_audio and os.path.exists(temp_audio):
                os.remove(temp_audio)
            return os.path.basename(fallback)
