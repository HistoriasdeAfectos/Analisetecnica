"""Backend MediaPipe Pose (API Tasks).

O MediaPipe ≥1.0 removeu `mp.solutions.pose`; o `PoseLandmarker` exige um
ficheiro de modelo `.task` local. Caminho procurado por omissão:

    models/pose_landmarker.task

Descarregável em
https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task
"""

from __future__ import annotations

import os

from ..keypoints import MEDIAPIPE_INDEX
from ..types import Point, PoseFrame, PoseSequence, View

DEFAULT_MODEL = os.path.join("models", "pose_landmarker.task")


class MediaPipeBackend:
    id = "mediapipe"

    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path or os.environ.get("ANALISETECNICA_POSE_MODEL", DEFAULT_MODEL)

    def detect(
        self,
        source: str,
        view: View,
        *,
        max_frames: int | None = None,
        **kwargs,
    ) -> PoseSequence:
        try:
            import cv2
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import (
                PoseLandmarker,
                PoseLandmarkerOptions,
                RunningMode,
            )
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise RuntimeError(
                "MediaPipe e OpenCV não estão instalados. "
                "Instalar com: pip install 'analisetecnica[pose]'"
            ) from exc

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"modelo de pose não encontrado em '{self.model_path}'. "
                "Descarregar pose_landmarker.task e apontar ANALISETECNICA_POSE_MODEL, "
                "ou usar --backend synthetic para experimentar o pipeline sem vídeo."
            )

        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise FileNotFoundError(f"não foi possível abrir o vídeo: {source}")
        fps = cap.get(cv2.CAP_PROP_FPS) or None

        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=self.model_path),
            running_mode=RunningMode.VIDEO,
            num_poses=1,
        )

        frames: list[PoseFrame] = []
        with PoseLandmarker.create_from_options(options) as landmarker:
            i = 0
            while True:
                ok, image = cap.read()
                if not ok or (max_frames and i >= max_frames):
                    break
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp_ms = int(1000 * i / (fps or 30.0))
                result = landmarker.detect_for_video(mp_image, timestamp_ms)

                kps: dict[str, Point] = {}
                if result.pose_landmarks:
                    landmarks = result.pose_landmarks[0]
                    for idx, name in MEDIAPIPE_INDEX.items():
                        if idx < len(landmarks):
                            lm = landmarks[idx]
                            kps[name] = Point(
                                x=float(lm.x),
                                y=float(lm.y),
                                confidence=float(getattr(lm, "visibility", 1.0) or 0.0),
                                z=float(getattr(lm, "z", 0.0) or 0.0),
                            )
                frames.append(PoseFrame(index=i, keypoints=kps))
                i += 1
        cap.release()

        return PoseSequence(
            frames=frames,
            view=view,
            fps=fps,
            source_id=os.path.basename(source),
            device={"backend": self.id, "model": os.path.basename(self.model_path)},
        )
