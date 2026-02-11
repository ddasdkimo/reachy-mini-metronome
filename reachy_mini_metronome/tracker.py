"""Hand tracking module using YOLOv8n-pose.

Detects wrist keypoints from camera frames and converts them
to head yaw/pitch angles for Reachy Mini to follow the user's hands.
"""

import numpy as np
from ultralytics import YOLO


class HandTracker:
    """Tracks hand (wrist) positions using YOLOv8n-pose."""

    # COCO pose keypoint indices
    LEFT_WRIST = 9
    RIGHT_WRIST = 10

    BODY_YAW_MAX_DEG = 30.0  # max body rotation for hand tracking
    BODY_SMOOTHING = 0.10  # heavier smoothing for stable base rotation

    def __init__(self, confidence: float = 0.5, smoothing: float = 0.35):
        self.model = YOLO("yolov8n-pose.pt")
        self.confidence = confidence
        self.smoothing = smoothing

        # Smoothed output
        self._yaw = 0.0
        self._pitch = 0.0
        self._body_yaw = 0.0  # smoothed body yaw (degrees)

        # Detection info (exposed to API)
        self.hands_detected = False
        self.num_wrists = 0

    def process_frame(self, frame: np.ndarray) -> tuple[float, float, float] | None:
        """Run pose detection and return (yaw_deg, pitch_deg, body_yaw_deg) or None."""
        results = self.model(frame, verbose=False, conf=self.confidence)

        if (
            not results
            or results[0].keypoints is None
            or len(results[0].keypoints.data) == 0
        ):
            self.hands_detected = False
            self.num_wrists = 0
            return None

        h, w = frame.shape[:2]

        # Collect confident wrist positions across all detected persons
        wrists: list[tuple[float, float]] = []
        for person_kpts in results[0].keypoints.data:
            for idx in (self.LEFT_WRIST, self.RIGHT_WRIST):
                x, y, conf = person_kpts[idx]
                if conf > self.confidence:
                    wrists.append((float(x), float(y)))

        if not wrists:
            self.hands_detected = False
            self.num_wrists = 0
            return None

        self.hands_detected = True
        self.num_wrists = len(wrists)

        # Average position of visible wrists
        avg_x = sum(p[0] for p in wrists) / len(wrists)
        avg_y = sum(p[1] for p in wrists) / len(wrists)

        # Normalize to [-1, 1]
        norm_x = (avg_x / w - 0.5) * 2
        norm_y = (avg_y / h - 0.5) * 2

        # Map to head angles (degrees)
        # Image left (norm_x<0) → robot looks left (positive yaw)
        raw_yaw = -norm_x * 35.0
        # Image bottom (norm_y>0) → robot looks down (positive pitch)
        raw_pitch = norm_y * 25.0

        # Body yaw: same direction as head yaw, larger range
        raw_body_yaw = -norm_x * self.BODY_YAW_MAX_DEG

        # Exponential moving average
        self._yaw += self.smoothing * (raw_yaw - self._yaw)
        self._pitch += self.smoothing * (raw_pitch - self._pitch)
        self._body_yaw += self.BODY_SMOOTHING * (raw_body_yaw - self._body_yaw)

        return (self._yaw, self._pitch, self._body_yaw)

    def reset(self) -> None:
        self._yaw = 0.0
        self._pitch = 0.0
        self._body_yaw = 0.0
        self.hands_detected = False
        self.num_wrists = 0
