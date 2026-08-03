"""Perfil de natação — crol. Ver docs/sports/natacao.md.

A vista `inferior` (câmara submersa por baixo do nadador) é a principal: por
estar totalmente dentro de água elimina a interface ar-água, restando apenas a
refracção da porta da caixa, que é calibrável.

Sem gerador sintético: este perfil só corre sobre vídeo real ou keypoints já
extraídos. É também o perfil onde é mais previsível que o backend genérico não
chegue e seja preciso um modelo afinado.
"""

from __future__ import annotations

from ..core.filtering import FilterSpec
from ..core.metrics import (
    BandTarget,
    MatchReferenceTarget,
    MaximizeTarget,
    MetricSpec,
    MinimizeTarget,
    Recommendation,
)
from ..core.profile import SportProfile, ViewSpec, register
from ..core.segmentation import CyclicSegmenter
from ..core.types import Laterality, Plane, Requires, View
from . import _common as C

INFERIOR, SUPERIOR, LATERAL = View.INFERIOR, View.SUPERIOR, View.LATERAL


def _segmenter() -> CyclicSegmenter:
    # Ciclo de braçada: entrada da mão direita a entrada seguinte da mesma mão.
    return CyclicSegmenter(
        signal=lambda fr: fr.get("right_wrist").x if fr.get("right_wrist") else float("nan"),
        cycle_event="hand_entry_right",
        kind="max",
        min_separation=15,
    )


METRICS = [
    MetricSpec(
        id="elbow_angle_catch",
        name="Ângulo do cotovelo na chamada",
        views=[INFERIOR],
        bases=["shoulder", "elbow", "wrist"],
        compute=C.angle_at_fraction(INFERIOR, "shoulder", "elbow", "wrist", 0.25),
        target=BandTarget(100.0, 140.0, tolerance=30.0),
        unit="°",
        bilateral=True,
        weight=1.5,
        group="braçada",
        recommendations=[
            Recommendation("above", "Cotovelo demasiado estendido na chamada: perde superfície de apoio — procurar cotovelo alto."),
        ],
    ),
    MetricSpec(
        id="high_elbow_index",
        name="Índice de cotovelo alto",
        views=[INFERIOR],
        bases=["elbow", "wrist"],
        compute=C.normalized_height_above(INFERIOR, "elbow", "wrist", scale="femur"),
        target=MaximizeTarget(0.35, 0.0),
        unit="ratio",
        bilateral=True,
        weight=2.0,
        group="braçada",
        recommendations=[
            Recommendation("below", "Cotovelo cai abaixo da mão na chamada: trabalhar antebraço vertical precoce."),
        ],
    ),
    MetricSpec(
        id="hand_path_width",
        name="Amplitude lateral da trajectória da mão",
        views=[INFERIOR],
        bases=["wrist", "shoulder"],
        compute=C.lateral_excursion(INFERIOR, "wrist", "shoulder", scale="shoulder"),
        target=BandTarget(0.25, 0.75, tolerance=0.40),
        unit="ratio",
        bilateral=True,
        weight=1.0,
        group="braçada",
    ),
    MetricSpec(
        id="stroke_rate",
        name="Frequência de braçada",
        views=[INFERIOR],
        bases=["wrist"],
        compute=C.cadence_steps_per_min(INFERIOR),
        target=MatchReferenceTarget(),
        unit="ciclos/min",
        requires=Requires.FPS,
        min_fps=30,
        weight=1.0,
        group="braçada",
    ),
    MetricSpec(
        id="body_roll",
        name="Rolamento do corpo",
        views=[INFERIOR],
        bases=["shoulder"],
        compute=C.bilateral_height_difference(INFERIOR, "shoulder", scale="shoulder"),
        target=BandTarget(0.30, 0.75, tolerance=0.35),
        unit="ratio",
        weight=1.5,
        group="posição do corpo",
    ),
    MetricSpec(
        id="hip_depth",
        name="Profundidade da anca",
        views=[LATERAL],
        bases=["hip", "shoulder"],
        compute=C.normalized_height_above(LATERAL, "shoulder", "hip", scale="stature"),
        target=MinimizeTarget(0.04, 0.16),
        unit="ratio",
        weight=2.0,
        group="posição do corpo",
        recommendations=[
            Recommendation("above", "Ancas baixas aumentam o arrasto: baixar o olhar e apoiar o peito na água."),
        ],
    ),
    MetricSpec(
        id="head_alignment",
        name="Alinhamento da cabeça",
        views=[LATERAL],
        bases=["shoulder", "ear", "nose"],
        compute=C.joint_angle(LATERAL, "shoulder", "ear", "nose"),
        target=BandTarget(110.0, 150.0, tolerance=30.0),
        unit="°",
        weight=1.0,
        group="posição do corpo",
    ),
    MetricSpec(
        id="lateral_deviation",
        name="Oscilação lateral do corpo",
        views=[SUPERIOR],
        bases=["hip", "shoulder"],
        compute=C.lateral_excursion(SUPERIOR, "hip", "shoulder", scale="shoulder"),
        target=MinimizeTarget(0.12, 0.50),
        unit="ratio",
        weight=1.0,
        group="posição do corpo",
        plane=Plane.TRANSVERSE,
    ),
    MetricSpec(
        id="kick_amplitude",
        name="Amplitude da pernada",
        views=[LATERAL],
        bases=["ankle", "hip"],
        compute=C.normalized_height_above(LATERAL, "ankle", "hip", scale="leg"),
        target=BandTarget(-0.15, 0.20, tolerance=0.25),
        unit="ratio",
        bilateral=True,
        weight=1.0,
        group="pernada",
    ),
    MetricSpec(
        id="knee_flexion_kick",
        name="Flexão do joelho na pernada",
        views=[LATERAL],
        bases=["hip", "knee", "ankle"],
        compute=C.joint_angle(LATERAL, "hip", "knee", "ankle", agg=min),
        target=BandTarget(130.0, 165.0, tolerance=25.0),
        unit="°",
        bilateral=True,
        weight=1.0,
        group="pernada",
        recommendations=[
            Recommendation("below", "Pernada demasiado de joelho: origem no quadril, com joelho mais estendido."),
        ],
    ),
    MetricSpec(
        id="stroke_symmetry",
        name="Simetria da braçada",
        views=[INFERIOR],
        bases=["wrist", "shoulder"],
        compute=C.lateral_excursion(INFERIOR, "wrist", "shoulder", scale="shoulder"),
        target=MinimizeTarget(0.10, 0.45),
        unit="ratio",
        weight=1.0,
        group="simetria e respiração",
    ),
]


PROFILE = register(
    SportProfile(
        id="natacao",
        name="Natação — crol",
        views=[
            ViewSpec(INFERIOR, required=True, laterality=Laterality.MIRRORED, plane=Plane.FRONTAL,
                     purpose="câmara submersa por baixo: trajectória das mãos, cotovelo alto, rolamento"),
            ViewSpec(SUPERIOR, required=False, laterality=Laterality.DIRECT, plane=Plane.TRANSVERSE,
                     purpose="entrada das mãos, alinhamento"),
            ViewSpec(LATERAL, required=False, laterality=Laterality.DIRECT, plane=Plane.SAGITTAL,
                     purpose="posição da anca, pernada"),
        ],
        segmenter=_segmenter,
        metrics=METRICS,
        filter_spec=FilterSpec(
            confidence_threshold=0.4,
            gap_interpolation="spline",
            max_gap_frames=6,
            smoothing="butterworth",
            order=4,
            cutoff_hz=5.0,
        ),
        group_weights={
            "braçada": 0.35,
            "posição do corpo": 0.30,
            "pernada": 0.15,
            "simetria e respiração": 0.20,
        },
        maturity="beta",
        min_repetitions=4,
        pose_backend="mediapipe",
        risks=[
            "Nadador submerso em decúbito ventral está fora da distribuição de treino do MediaPipe; prever backend afinado.",
            "Turbulência e bolhas ocluem os membros nas fases mais informativas.",
            "Calibração tem de ser feita debaixo de água — a calibração em ar não é válida.",
            "As marcações regulamentares da piscina servem de referência métrica permanente.",
        ],
    )
)
