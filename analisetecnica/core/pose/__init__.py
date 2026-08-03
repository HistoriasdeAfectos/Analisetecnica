"""Backends de pose. Adaptadores intermutáveis (ARCHITECTURE.md §2.4).

A camada de métricas nunca acede a um backend directamente — só ao esquema
canónico de keypoints. É isso que permite trocar de detector (ou usar um modelo
afinado para natação) sem tocar em nenhuma métrica.
"""

from __future__ import annotations

from typing import Protocol

from ..types import PoseSequence, View


class PoseBackend(Protocol):
    id: str

    def detect(self, source: str, view: View, **kwargs) -> PoseSequence: ...


def load(backend_id: str) -> PoseBackend:
    if backend_id in ("mediapipe", "mediapipe_pose"):
        from .mediapipe_backend import MediaPipeBackend

        return MediaPipeBackend()
    if backend_id == "synthetic":
        from .synthetic import SyntheticBackend

        return SyntheticBackend()
    raise KeyError(f"backend de pose desconhecido: {backend_id}")
