"""Esquema canónico de keypoints e resolução de lateralidade.

O esquema canónico é interno. Cada `PoseBackend` traduz a sua própria numeração
para estes nomes, de modo que a camada de métricas nunca dependa do backend.
"""

from __future__ import annotations

from .types import Laterality, Side

# Nomes canónicos. Os pares esquerda/direita usam o prefixo `left_`/`right_`.
CANONICAL = [
    "nose",
    "left_eye", "right_eye",
    "left_ear", "right_ear",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
    "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]

# Índices do MediaPipe Pose (33 landmarks) para os nomes canónicos.
MEDIAPIPE_INDEX = {
    0: "nose",
    2: "left_eye", 5: "right_eye",
    7: "left_ear", 8: "right_ear",
    11: "left_shoulder", 12: "right_shoulder",
    13: "left_elbow", 14: "right_elbow",
    15: "left_wrist", 16: "right_wrist",
    23: "left_hip", 24: "right_hip",
    25: "left_knee", 26: "right_knee",
    27: "left_ankle", 28: "right_ankle",
    29: "left_heel", 30: "right_heel",
    31: "left_foot_index", 32: "right_foot_index",
}


def resolve(base: str, side: Side | None, laterality: Laterality) -> str:
    """Resolve um nome com lado para o nome canónico, aplicando a vista.

    Os modelos de pose rotulam keypoints anatomicamente assumindo um sujeito
    virado para a câmara. Nas vistas `posterior` e `inferior` esse pressuposto
    inverte-se, e os rótulos do modelo têm de ser trocados. Trocar isto ao
    contrário inverte silenciosamente toda a análise de simetria — ver
    CLAUDE.md, secção "Armadilhas específicas".
    """
    if side is None:
        return base
    effective = side
    if laterality is Laterality.MIRRORED:
        effective = Side.RIGHT if side is Side.LEFT else Side.LEFT
    return f"{effective.value}_{base}"


def opposite(side: Side) -> Side:
    return Side.RIGHT if side is Side.LEFT else Side.LEFT
