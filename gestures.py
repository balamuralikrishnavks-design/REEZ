"""REEZ hand gestures: the camera watches one hand and reports gestures and up/down movement."""

import math
import threading
import time
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).parent
MODEL = BASE / "models" / "hand_landmarker.task"
CAMERA_FILE = BASE / "data" / "camera.txt"

CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]
HOLD = 0.6       # seconds a gesture must be held before it counts
COOLDOWN = 1.5   # seconds before the next gesture can fire
STEP = 0.045     # hand movement (fraction of the picture height) for one adjust step


def _camera_index():
    try:
        return int(CAMERA_FILE.read_text().strip())
    except Exception:
        return 0


def _d(p, i, j):
    return math.hypot(p[i].x - p[j].x, p[i].y - p[j].y)


def fingers(p):
    """Which fingers are stretched out: thumb, index, middle, ring, pinky."""
    thumb = _d(p, 4, 17) > _d(p, 3, 17) * 1.1
    others = [_d(p, tip, 0) > _d(p, pip, 0) * 1.05 for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18))]
    return [thumb] + others


def classify(p):
    thumb, index, middle, ring, pinky = fingers(p)
    count = sum((index, middle, ring, pinky))
    palm = max(1e-6, _d(p, 0, 9))
    if count == 4:
        return "open"
    if count == 0:
        if thumb and p[4].y < p[0].y - 0.7 * palm:
            return "thumbs_up"
        return "fist"
    if count == 2 and index and middle:
        return "peace"
    if count == 1 and index:
        return "point"
    return ""


class GestureEngine(threading.Thread):
    def __init__(self, on_event, on_frame=None):
        super().__init__(daemon=True)
        self.on_event = on_event
        self.on_frame = on_frame
        self.running = True
        self.preview = False
        self.adjusting = False
        self.ok = False

    def _event(self, kind, value):
        try:
            self.on_event(kind, value)
        except Exception:
            pass

    def run(self):
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
        except Exception as error:
            self._event("status", "Gestures need mediapipe: " + str(error)[:60])
            return
        if not MODEL.exists():
            self._event("status", "The gesture model is missing: models/hand_landmarker.task")
            return
        try:
            landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(MODEL)),
                running_mode=vision.RunningMode.VIDEO, num_hands=1,
                min_hand_detection_confidence=0.6, min_hand_presence_confidence=0.6,
                min_tracking_confidence=0.5))
        except Exception as error:
            self._event("status", "Gestures could not start: " + str(error)[:60])
            return
        cap = cv2.VideoCapture(_camera_index(), cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(_camera_index())
        if not cap.isOpened():
            self._event("status", "I cannot open the camera.")
            landmarker.close()
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.ok = True
        self._event("status", "Hand gestures are on.")
        t0 = time.time()
        last_stamp = 0
        held, held_since, fired, last_fire = "", 0.0, False, 0.0
        anchor = None
        while self.running:
            began = time.time()
            good, frame = cap.read()
            if not good:
                time.sleep(0.05)
                continue
            frame = cv2.flip(frame, 1)
            rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            stamp = max(last_stamp + 1, int((time.time() - t0) * 1000))
            last_stamp = stamp
            try:
                result = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), stamp)
            except Exception:
                continue
            points = result.hand_landmarks[0] if result.hand_landmarks else None
            name = ""
            now = time.time()
            if points:
                name = classify(points)
                cy = sum(points[i].y for i in (0, 5, 9, 13, 17)) / 5.0
                if self.adjusting and name == "open":
                    if anchor is None:
                        anchor = cy
                    delta = anchor - cy
                    if abs(delta) >= STEP:
                        self._event("adjust", 1 if delta > 0 else -1)
                        anchor = cy
                else:
                    anchor = None
                if self.adjusting and name == "open":
                    held, fired = "", False
                elif name != held:
                    held, held_since, fired = name, now, False
                elif name and not fired and now - held_since >= HOLD and now - last_fire >= COOLDOWN:
                    fired = True
                    last_fire = now
                    self._event("gesture", name)
            else:
                anchor = None
                held, fired = "", False
            if self.preview and self.on_frame is not None:
                small = cv2.resize(frame, (320, 240))
                if points:
                    pts = [(int(q.x * 320), int(q.y * 240)) for q in points]
                    for a, b in CONNECTIONS:
                        cv2.line(small, pts[a], pts[b], (247, 85, 168), 2)
                    for pt in pts:
                        cv2.circle(small, pt, 3, (255, 213, 233), -1)
                label = name or ("hand" if points else "no hand")
                if self.adjusting:
                    label += "  (adjusting)"
                cv2.putText(small, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                try:
                    self.on_frame(cv2.cvtColor(small, cv2.COLOR_BGR2RGB).tobytes(), 320, 240)
                except Exception:
                    pass
            time.sleep(max(0.0, 0.066 - (time.time() - began)))
        cap.release()
        landmarker.close()
        self.ok = False
