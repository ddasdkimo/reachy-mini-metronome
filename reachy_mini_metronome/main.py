"""Reachy Mini Metronome with Practice Timer and Hand Tracking.

Features:
- Mirror antenna motion (both antennas swing in opposite directions)
- BPM range: 40-208
- Time signature support (2/4, 3/4, 4/4, 5/4, 6/8)
- Accented downbeat (higher pitch click on beat 1)
- Practice timer: tracks session duration and total accumulated practice time
- Hand tracking: YOLOv8n-pose wrist detection, robot head follows user's hands
"""

import threading
import time

import numpy as np
from pydantic import BaseModel

from reachy_mini import ReachyMini, ReachyMiniApp
from reachy_mini.utils import create_head_pose

from fastapi.responses import FileResponse

from .audio import MetronomeAudio
from .midi import MidiHandler
from .recorder import PracticeRecorder
from .tracker import HandTracker


class BpmUpdate(BaseModel):
    bpm: int


class TimeSignatureUpdate(BaseModel):
    beats: int


class SmoothingUpdate(BaseModel):
    value: float


class MidiPortSelect(BaseModel):
    port_name: str


class MidiAmplitude(BaseModel):
    value: float


class ReachyMiniMetronome(ReachyMiniApp):
    """Metronome application for Reachy Mini with practice timer and hand tracking."""

    custom_app_url: str | None = "http://0.0.0.0:8042"

    # Constants
    MIN_BPM = 40
    MAX_BPM = 208
    DEFAULT_BPM = 120
    DEFAULT_TIME_SIGNATURE = 4
    ANTENNA_AMPLITUDE_DEG = 35.0
    LOOP_INTERVAL = 0.01
    TRACK_INTERVAL = 0.05  # 20 FPS for hand tracking

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        # Initialize audio system
        sample_rate = reachy_mini.media.get_output_audio_samplerate()
        audio = MetronomeAudio(sample_rate)

        # Metronome state
        bpm = self.DEFAULT_BPM
        time_signature = self.DEFAULT_TIME_SIGNATURE
        current_beat = 1
        display_beat = 1
        is_running = False

        # Timing variables
        start_time = 0.0
        next_beat_time = 0.0

        # Practice timer state
        practice_session_start = 0.0
        practice_total_seconds = 0.0
        practice_sessions: list[dict] = []

        # Hand tracking state
        tracking_enabled = False
        tracker: HandTracker | None = None
        last_track_time = 0.0

        # MIDI state
        midi_enabled = False
        midi_handler = MidiHandler()

        # Shared lock for camera access across threads
        frame_lock = threading.Lock()

        # Recorder
        recorder = PracticeRecorder(frame_lock=frame_lock)

        amplitude_rad = np.deg2rad(self.ANTENNA_AMPLITUDE_DEG)

        # -----------------------------------------------------------
        # Metronome API Endpoints
        # -----------------------------------------------------------

        @self.settings_app.post("/bpm")
        def set_bpm(data: BpmUpdate) -> dict:
            nonlocal bpm
            bpm = max(self.MIN_BPM, min(self.MAX_BPM, data.bpm))
            return {"bpm": bpm}

        @self.settings_app.post("/time_signature")
        def set_time_signature(data: TimeSignatureUpdate) -> dict:
            nonlocal time_signature, current_beat, display_beat
            time_signature = max(2, min(8, data.beats))
            current_beat = 1
            display_beat = 1
            return {"time_signature": time_signature}

        @self.settings_app.post("/start")
        def start() -> dict:
            nonlocal is_running, start_time, next_beat_time
            nonlocal current_beat, display_beat, practice_session_start
            if not is_running:
                is_running = True
                start_time = time.perf_counter()
                next_beat_time = start_time
                current_beat = 1
                display_beat = 1
                practice_session_start = time.time()
            return {"running": True}

        @self.settings_app.post("/stop")
        def stop() -> dict:
            nonlocal is_running, current_beat, display_beat
            nonlocal practice_total_seconds, practice_session_start
            if is_running:
                session_duration = time.time() - practice_session_start
                practice_total_seconds += session_duration
                practice_sessions.append({
                    "duration": round(session_duration, 1),
                    "bpm": bpm,
                    "time_signature": time_signature,
                })
            is_running = False
            current_beat = 1
            display_beat = 1
            reachy_mini.set_target(antennas=[0.0, 0.0])
            return {"running": False}

        @self.settings_app.get("/status")
        def get_status() -> dict:
            current_session_seconds = 0.0
            if is_running:
                current_session_seconds = time.time() - practice_session_start
            return {
                "bpm": bpm,
                "time_signature": time_signature,
                "current_beat": display_beat,
                "running": is_running,
                "practice": {
                    "current_session": round(current_session_seconds, 1),
                    "total": round(practice_total_seconds + current_session_seconds, 1),
                    "session_count": len(practice_sessions) + (1 if is_running else 0),
                },
                "tracking": {
                    "enabled": tracking_enabled,
                    "hands_detected": tracker.hands_detected if tracker else False,
                    "num_wrists": tracker.num_wrists if tracker else 0,
                    "smoothing": tracker.smoothing if tracker else 0.35,
                },
                "recording": {
                    "state": recorder.state,
                    "elapsed": round(recorder.elapsed, 1),
                },
                "midi": {
                    "enabled": midi_enabled,
                    "port": midi_handler.port_name,
                    "last_note": midi_handler.last_note,
                    "last_note_name": midi_handler.last_note_name,
                    "last_velocity": midi_handler.last_velocity,
                    "body_yaw": round(midi_handler.body_pos, 1),
                    "notes_count": midi_handler.notes_count,
                    "amplitude": round(midi_handler.amplitude_mult, 2),
                },
            }

        @self.settings_app.post("/practice/reset")
        def reset_practice() -> dict:
            nonlocal practice_total_seconds, practice_session_start
            practice_total_seconds = 0.0
            practice_sessions.clear()
            if is_running:
                practice_session_start = time.time()
            return {"reset": True}

        @self.settings_app.get("/practice/history")
        def get_practice_history() -> dict:
            return {
                "sessions": practice_sessions,
                "total": round(practice_total_seconds, 1),
            }

        # -----------------------------------------------------------
        # Tracking API Endpoints
        # -----------------------------------------------------------

        @self.settings_app.post("/tracking/start")
        def start_tracking() -> dict:
            nonlocal tracking_enabled, tracker
            if tracker is None:
                tracker = HandTracker()
            tracker.reset()
            tracking_enabled = True
            return {"tracking": True}

        @self.settings_app.post("/tracking/stop")
        def stop_tracking() -> dict:
            nonlocal tracking_enabled
            tracking_enabled = False
            # Return head to neutral
            head_pose = create_head_pose(yaw=0, pitch=0, degrees=True)
            reachy_mini.set_target(head=head_pose)
            return {"tracking": False}

        @self.settings_app.post("/tracking/smoothing")
        def set_smoothing(data: SmoothingUpdate) -> dict:
            nonlocal tracker
            val = max(0.05, min(1.0, data.value))
            if tracker is None:
                tracker = HandTracker(smoothing=val)
            else:
                tracker.smoothing = val
            return {"smoothing": val}

        # -----------------------------------------------------------
        # MIDI API Endpoints
        # -----------------------------------------------------------

        @self.settings_app.get("/midi/ports")
        def get_midi_ports() -> dict:
            return {"ports": midi_handler.list_ports()}

        @self.settings_app.post("/midi/start")
        def start_midi(data: MidiPortSelect) -> dict:
            nonlocal midi_enabled
            ok = midi_handler.open(data.port_name)
            midi_enabled = ok
            return {"enabled": ok, "port": midi_handler.port_name}

        @self.settings_app.post("/midi/stop")
        def stop_midi() -> dict:
            nonlocal midi_enabled
            midi_handler.close()
            midi_enabled = False
            # Reset body and head to neutral
            reachy_mini.set_target(body_yaw=0.0)
            if not tracking_enabled:
                head_pose = create_head_pose(yaw=0, pitch=0, degrees=True)
                reachy_mini.set_target(head=head_pose)
            return {"enabled": False}

        @self.settings_app.get("/midi/status")
        def get_midi_status() -> dict:
            return {
                "enabled": midi_enabled,
                "port": midi_handler.port_name,
                "last_note": midi_handler.last_note,
                "last_note_name": midi_handler.last_note_name,
                "last_velocity": midi_handler.last_velocity,
                "body_yaw": round(midi_handler.body_pos, 1),
                "head_pitch": round(midi_handler.head_pitch_pos, 1),
                "notes_count": midi_handler.notes_count,
                "amplitude": round(midi_handler.amplitude_mult, 2),
            }

        @self.settings_app.post("/midi/amplitude")
        def set_midi_amplitude(data: MidiAmplitude) -> dict:
            midi_handler.amplitude_mult = data.value
            return {"amplitude": round(midi_handler.amplitude_mult, 2)}

        # -----------------------------------------------------------
        # Recording API Endpoints
        # -----------------------------------------------------------

        @self.settings_app.post("/recording/start")
        def start_recording() -> dict:
            ok = recorder.start(reachy_mini)
            return {"recording": ok, "state": recorder.state}

        @self.settings_app.post("/recording/stop")
        def stop_recording() -> dict:
            recorder.stop()
            return {"state": recorder.state}

        @self.settings_app.get("/recording/list")
        def list_recordings() -> dict:
            return {"files": recorder.list_recordings()}

        @self.settings_app.get("/recording/download/{filename}")
        def download_recording(filename: str):
            path = recorder.get_file_path(filename)
            if path:
                return FileResponse(path, filename=filename, media_type="video/mp4")
            return {"error": "not found"}

        @self.settings_app.delete("/recording/{filename}")
        def delete_recording(filename: str) -> dict:
            ok = recorder.delete_recording(filename)
            return {"deleted": ok}

        # -----------------------------------------------------------
        # Main Loop
        # -----------------------------------------------------------

        while not stop_event.is_set():
            now = time.perf_counter()

            # ── Metronome logic ──
            if is_running:
                if now >= next_beat_time:
                    display_beat = current_beat

                    is_downbeat = current_beat == 1
                    audio.play_click(is_downbeat, reachy_mini)

                    current_beat = (current_beat % time_signature) + 1
                    next_beat_time += 60.0 / bpm

                # Antenna motion
                beats_per_second = bpm / 60.0
                elapsed = now - start_time
                phase = (elapsed * beats_per_second / 2) % 1.0

                right_angle = amplitude_rad * np.sin(2 * np.pi * phase)
                left_angle = -right_angle

                reachy_mini.set_target(antennas=[right_angle, left_angle])

            # ── Hand tracking logic (20 FPS) ──
            if tracking_enabled and tracker and (now - last_track_time >= self.TRACK_INTERVAL):
                last_track_time = now
                try:
                    with frame_lock:
                        frame = reachy_mini.media.get_frame()
                    if frame is not None:
                        result = tracker.process_frame(frame)
                        if result is not None:
                            yaw, pitch = result
                            head_pose = create_head_pose(
                                yaw=yaw, pitch=pitch, degrees=True
                            )
                            reachy_mini.set_target(head=head_pose)
                except Exception:
                    pass  # Skip frame on camera error

            # ── MIDI rhythm body/head motion ──
            if midi_enabled and midi_handler.is_open:
                body_yaw_deg, head_yaw_deg, head_pitch_deg = midi_handler.update(
                    self.LOOP_INTERVAL
                )
                body_yaw_rad = np.deg2rad(body_yaw_deg)
                reachy_mini.set_target(body_yaw=body_yaw_rad)
                # Head: only if hand tracking is OFF (avoid conflict)
                if not tracking_enabled:
                    head_pose = create_head_pose(
                        yaw=head_yaw_deg, pitch=head_pitch_deg, degrees=True
                    )
                    reachy_mini.set_target(head=head_pose)

            time.sleep(self.LOOP_INTERVAL)

        # Cleanup
        if midi_enabled:
            midi_handler.close()

        if recorder.state == recorder.STATE_RECORDING:
            recorder.stop()

        if is_running:
            session_duration = time.time() - practice_session_start
            practice_total_seconds += session_duration

        audio.stop(reachy_mini)


if __name__ == "__main__":
    app = ReachyMiniMetronome()
    app.wrapped_run()
