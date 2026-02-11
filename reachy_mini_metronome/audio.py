"""Audio generation module for the Reachy Mini Metronome.

Handles synthesized click sound generation and playback.
Clicks are pre-generated at initialization for low-latency playback.
"""

import numpy as np
import numpy.typing as npt

from reachy_mini import ReachyMini


def generate_click(
    frequency: float,
    duration_ms: float,
    amplitude: float,
    sample_rate: int,
) -> npt.NDArray[np.float32]:
    """Generate a click sound as np.float32 array."""
    num_samples = int(sample_rate * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, num_samples, dtype=np.float32)

    wave = amplitude * np.sin(2 * np.pi * frequency * t).astype(np.float32)

    # Apply envelope (10% attack, 90% decay) for clean sound
    envelope = np.ones(num_samples, dtype=np.float32)
    attack_samples = int(num_samples * 0.1)
    if attack_samples > 0:
        envelope[:attack_samples] = np.linspace(0, 1, attack_samples, dtype=np.float32)
    if num_samples - attack_samples > 0:
        envelope[attack_samples:] = np.linspace(
            1, 0, num_samples - attack_samples, dtype=np.float32
        )

    return wave * envelope


class MetronomeAudio:
    """Handles metronome click sound generation and playback."""

    NORMAL_FREQUENCY = 800
    NORMAL_DURATION = 30
    NORMAL_AMPLITUDE = 0.5

    ACCENT_FREQUENCY = 1200
    ACCENT_DURATION = 40
    ACCENT_AMPLITUDE = 0.8

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self._playing_started = False

        self.normal_click = generate_click(
            self.NORMAL_FREQUENCY,
            self.NORMAL_DURATION,
            self.NORMAL_AMPLITUDE,
            sample_rate,
        )
        self.accent_click = generate_click(
            self.ACCENT_FREQUENCY,
            self.ACCENT_DURATION,
            self.ACCENT_AMPLITUDE,
            sample_rate,
        )

    def play_click(self, is_downbeat: bool, reachy_mini: ReachyMini) -> None:
        if not self._playing_started:
            reachy_mini.media.start_playing()
            self._playing_started = True

        click = self.accent_click if is_downbeat else self.normal_click
        reachy_mini.media.push_audio_sample(click)

    def stop(self, reachy_mini: ReachyMini) -> None:
        if self._playing_started:
            reachy_mini.media.stop_playing()
            self._playing_started = False
