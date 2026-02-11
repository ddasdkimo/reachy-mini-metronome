"""MIDI keyboard handler for rhythm-driven robot body/head motion.

Listens for Note On/Off and CC messages from a MIDI input device.
Each Note On triggers an impulse that produces body sway and head nod
using a spring-damper physics model for natural movement.
"""

import math
import threading
import time

try:
    import mido

    _MIDO_AVAILABLE = True
except ImportError:
    _MIDO_AVAILABLE = False


# MIDI note names for display
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _note_name(note: int) -> str:
    octave = (note // 12) - 1
    return f"{_NOTE_NAMES[note % 12]}{octave}"


class MidiHandler:
    """Processes MIDI input and produces body/head motion via spring-damper physics."""

    MAX_BODY_SWAY_DEG = 20.0
    MAX_NOD_DEG = 12.0
    DECAY_RATE = 4.0  # exponential decay per second
    SPRING_FACTOR = 12.0
    HEAD_YAW_RATIO = 0.3  # head yaw follows body sway at this ratio

    def __init__(self) -> None:
        self._port = None
        self._port_name = ""
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

        # Movement state
        self._body_target = 0.0  # target body yaw (deg)
        self._body_pos = 0.0  # current body yaw (deg)
        self._head_pitch_impulse = 0.0  # pending nod impulse (deg)
        self._head_pitch_pos = 0.0  # current head pitch (deg)
        self._head_yaw_pos = 0.0  # current head yaw (deg)
        self._sway_direction = 1  # alternates +1 / -1

        # CC modifiers
        self._amplitude_mult = 1.0  # CC#1 (mod wheel) — 0..2
        self._max_sway = self.MAX_BODY_SWAY_DEG  # CC#7
        self._decay_rate = self.DECAY_RATE  # CC#11

        # Status (read from main thread)
        self._last_note = 0
        self._last_velocity = 0
        self._last_note_name = ""
        self._notes_count = 0
        self._last_note_time = 0.0  # time.time() of last Note On

    # ── Public properties ──

    @property
    def is_open(self) -> bool:
        return self._port is not None and self._running

    @property
    def port_name(self) -> str:
        return self._port_name

    @property
    def last_note(self) -> int:
        return self._last_note

    @property
    def last_note_name(self) -> str:
        return self._last_note_name

    @property
    def last_velocity(self) -> int:
        return self._last_velocity

    @property
    def notes_count(self) -> int:
        return self._notes_count

    @property
    def last_note_time(self) -> float:
        return self._last_note_time

    @property
    def seconds_since_last_note(self) -> float:
        """Seconds elapsed since the last Note On (0 if no note yet)."""
        if self._last_note_time == 0.0:
            return 0.0
        return time.time() - self._last_note_time

    @property
    def body_pos(self) -> float:
        return self._body_pos

    @property
    def head_pitch_pos(self) -> float:
        return self._head_pitch_pos

    @property
    def head_yaw_pos(self) -> float:
        return self._head_yaw_pos

    @property
    def amplitude_mult(self) -> float:
        return self._amplitude_mult

    @amplitude_mult.setter
    def amplitude_mult(self, value: float) -> None:
        self._amplitude_mult = max(0.0, min(2.0, value))

    # ── Port management ──

    @staticmethod
    def list_ports() -> list[str]:
        """Return available MIDI input port names."""
        if not _MIDO_AVAILABLE:
            return []
        try:
            return mido.get_input_names()
        except Exception:
            return []

    def open(self, port_name: str) -> bool:
        """Open *port_name* and start the background listener thread."""
        if not _MIDO_AVAILABLE:
            return False
        self.close()
        try:
            self._port = mido.open_input(port_name)
        except Exception:
            return False
        self._port_name = port_name
        self._running = True
        self._thread = threading.Thread(target=self._listener, daemon=True)
        self._thread.start()
        return True

    def close(self) -> None:
        """Stop listening and close the port."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None
        self._port_name = ""
        # Reset motion state
        with self._lock:
            self._body_target = 0.0
            self._body_pos = 0.0
            self._head_pitch_impulse = 0.0
            self._head_pitch_pos = 0.0
            self._head_yaw_pos = 0.0
            self._sway_direction = 1

    # ── Background listener ──

    def _listener(self) -> None:
        """Read MIDI messages in a background thread."""
        while self._running and self._port is not None:
            try:
                for msg in self._port.iter_pending():
                    if not self._running:
                        break
                    self._handle_message(msg)
            except Exception:
                pass
            time.sleep(0.001)  # ~1 ms poll

    def _handle_message(self, msg) -> None:
        if msg.type == "note_on" and msg.velocity > 0:
            self._on_note_on(msg.note, msg.velocity)
        elif msg.type == "control_change":
            self._on_cc(msg.control, msg.value)

    def _on_note_on(self, note: int, velocity: int) -> None:
        vel_norm = velocity / 127.0
        max_sway = self._max_sway * self._amplitude_mult

        # Pitch-dependent scaling (optional)
        body_scale = 1.0
        head_scale = 1.0
        if note <= 48:  # C2-C3: bigger body sway
            body_scale = 1.3
            head_scale = 0.7
        elif note >= 72:  # C5-C6: bigger head motion
            body_scale = 0.7
            head_scale = 1.3

        with self._lock:
            # Alternating body sway direction
            direction = self._sway_direction
            self._sway_direction *= -1

            sway_deg = vel_norm * max_sway * body_scale
            self._body_target = direction * sway_deg

            # Head nod impulse
            nod_deg = vel_norm * self.MAX_NOD_DEG * head_scale * self._amplitude_mult
            self._head_pitch_impulse = nod_deg

            # Status
            self._last_note = note
            self._last_velocity = velocity
            self._last_note_name = _note_name(note)
            self._notes_count += 1
            self._last_note_time = time.time()

    def _on_cc(self, control: int, value: int) -> None:
        norm = value / 127.0
        if control == 1:  # Mod Wheel → amplitude multiplier 0..2
            self._amplitude_mult = norm * 2.0
        elif control == 7:  # Volume → max sway 5..40 deg
            self._max_sway = 5.0 + norm * 35.0
        elif control == 11:  # Expression → decay rate 1..10
            self._decay_rate = 1.0 + norm * 9.0

    # ── Physics update (called from main loop) ──

    def update(self, dt: float) -> tuple[float, float, float]:
        """Advance the spring-damper model by *dt* seconds.

        Returns (body_yaw_deg, head_yaw_deg, head_pitch_deg).
        """
        with self._lock:
            # Body sway: spring toward target, then target decays to 0
            spring = self.SPRING_FACTOR
            self._body_pos += (self._body_target - self._body_pos) * spring * dt
            decay = math.exp(-self._decay_rate * dt)
            self._body_target *= decay

            # Also let body_pos itself decay (prevents accumulation)
            self._body_pos *= decay

            # Head yaw follows body sway
            self._head_yaw_pos = self._body_pos * self.HEAD_YAW_RATIO

            # Head pitch nod: rapid attack, then decay
            if self._head_pitch_impulse > 0:
                # Quick down-press
                self._head_pitch_pos += (
                    self._head_pitch_impulse - self._head_pitch_pos
                ) * spring * 2.0 * dt
                self._head_pitch_impulse *= math.exp(-8.0 * dt)
                if self._head_pitch_impulse < 0.3:
                    self._head_pitch_impulse = 0.0
            else:
                # Elastic return to neutral
                self._head_pitch_pos *= math.exp(-6.0 * dt)

            return (self._body_pos, self._head_yaw_pos, self._head_pitch_pos)
