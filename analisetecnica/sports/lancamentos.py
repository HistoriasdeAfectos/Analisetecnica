"""Perfil de lançamentos. Ver docs/sports/lancamentos.md.

`maturity: experimental`. As métricas de largada (ângulo, velocidade) exigem
tracking do engenho e calibração métrica, e não estão implementadas: sem elas o
score é explicitamente **parcial**. Um ângulo de largada errado é pior do que
ângulo nenhum, porque orienta o treino na direcção errada.

Sem gerador sintético — só vídeo real ou keypoints já extraídos.
"""

from __future__ import annotations

from ..core.filtering import FilterSpec
from ..core.metrics import (
    BandTarget,
    MaximizeTarget,
    MetricContext,
    MetricSpec,
    MinimizeTarget,
    Recommendation,
)
from ..core.profile import SportProfile, ViewSpec, register
from ..core.segmentation import PhaseSegmenter
from ..core.types import Laterality, Plane, PoseSequence, Requires, View
from . import _common as C

LATERAL, POSTERIOR, SUPERIOR = View.LATERAL, View.POSTERIOR, View.SUPERIOR


def _release_detector(seq: PoseSequence) -> list[int]:
    """Largada aproximada pela extensão máxima do punho de lançamento.

    Enquanto não houver tracking do engenho, este é um substituto assumidamente
    grosseiro: a largada real acontece alguns frames depois, e a 240 fps essa
    diferença é material para qualquer métrica de velocidade.
    """
    n = len(seq.frames)
    if n < 8:
        return []
    reach = []
    for fr in seq.frames:
        w = fr.get("right_wrist")
        s = fr.get("right_shoulder")
        reach.append(abs(w.x - s.x) if (w and s) else float("nan"))
    best, idx = float("-inf"), None
    for i, v in enumerate(reach):
        if v == v and v > best:
            best, idx = v, i
    return [idx] if idx is not None else []


def _segmenter() -> PhaseSegmenter:
    return PhaseSegmenter(
        phases=["setup", "approach", "power_position", "delivery", "release"],
        anchor_event="release",
        anchor_detector=_release_detector,
        pre_frames=120,
        post_frames=40,
        repetition_label="throw",
    )


def _delivery_time_ms():
    def compute(ctx: MetricContext) -> list[float]:
        fps = ctx.fps
        if not fps:
            return []
        out = []
        for seg in ctx.segments:
            pp = seg.events.get("power_position")
            rel = seg.events.get("release")
            if pp is None or rel is None or rel <= pp:
                continue
            out.append(1000.0 * (rel - pp) / fps)
        return out

    return compute


METRICS = [
    MetricSpec(
        id="hip_shoulder_separation",
        name="Separação anca-ombro na posição de força",
        views=[SUPERIOR],
        bases=["hip", "shoulder"],
        compute=C.line_angle_difference(SUPERIOR, ("hip", "hip"), ("shoulder", "shoulder"), at_fraction=0.70),
        target=MaximizeTarget(30.0, 5.0),
        unit="°",
        weight=2.0,
        group="posição de força",
        plane=Plane.TRANSVERSE,
        caveat="Depende de deteção zenital, fora da distribuição de treino do MediaPipe.",
        recommendations=[
            Recommendation("below", "Pouca separação entre ancas e ombros: o tronco roda cedo demais e perde-se armazenamento elástico."),
        ],
    ),
    MetricSpec(
        id="trunk_lean_release",
        name="Inclinação do tronco na largada",
        views=[LATERAL],
        bases=["hip", "shoulder"],
        compute=C.trunk_to_vertical(LATERAL),
        target=BandTarget(5.0, 25.0, tolerance=18.0),
        unit="°",
        weight=1.0,
        group="posição de força",
    ),
    MetricSpec(
        id="block_leg_angle",
        name="Ângulo da perna de bloqueio na largada",
        views=[LATERAL],
        bases=["hip", "knee", "ankle"],
        compute=C.angle_at_fraction(LATERAL, "hip", "knee", "ankle", 0.75),
        target=BandTarget(155.0, 178.0, tolerance=25.0),
        unit="°",
        weight=2.0,
        group="bloqueio e entrega",
        recommendations=[
            Recommendation("below", "Perna de bloqueio cede na largada: a energia dissipa-se em vez de transferir para o engenho."),
        ],
    ),
    MetricSpec(
        id="delivery_time",
        name="Tempo de entrega",
        views=[LATERAL],
        bases=["wrist"],
        compute=_delivery_time_ms(),
        target=MinimizeTarget(220.0, 600.0),
        unit="ms",
        requires=Requires.FPS,
        min_fps=120,
        weight=1.0,
        group="bloqueio e entrega",
    ),
    MetricSpec(
        id="release_height",
        name="Altura da largada",
        views=[LATERAL],
        bases=["wrist", "hip"],
        compute=C.normalized_height_above(LATERAL, "wrist", "hip", scale="stature"),
        target=MaximizeTarget(0.42, 0.15),
        unit="ratio",
        min_fps=240,
        requires=Requires.FPS,
        weight=1.5,
        group="parâmetros de largada",
        caveat="Instante de largada estimado pela extensão do punho — aproximação até haver tracking do engenho.",
    ),
    MetricSpec(
        id="com_path_deviation",
        name="Desvio lateral do centro de massa",
        views=[POSTERIOR],
        bases=["hip", "shoulder"],
        compute=C.lateral_excursion(POSTERIOR, "shoulder", "hip", scale="shoulder"),
        target=MinimizeTarget(0.15, 0.60),
        unit="ratio",
        weight=1.0,
        group="aproximação",
        plane=Plane.FRONTAL,
    ),
]


PROFILE = register(
    SportProfile(
        id="lancamentos",
        name="Atletismo — lançamentos",
        views=[
            ViewSpec(LATERAL, required=True, laterality=Laterality.DIRECT, plane=Plane.SAGITTAL,
                     purpose="bloqueio, tronco, altura de largada"),
            ViewSpec(POSTERIOR, required=False, laterality=Laterality.MIRRORED, plane=Plane.FRONTAL,
                     purpose="alinhamento e deslocamento lateral"),
            ViewSpec(SUPERIOR, required=False, laterality=Laterality.DIRECT, plane=Plane.TRANSVERSE,
                     purpose="separação anca-ombro"),
        ],
        segmenter=_segmenter,
        metrics=METRICS,
        filter_spec=FilterSpec(
            confidence_threshold=0.5,
            gap_interpolation="linear",
            max_gap_frames=2,
            smoothing="butterworth",
            order=4,
            cutoff_hz=12.0,
        ),
        group_weights={
            "parâmetros de largada": 0.35,
            "posição de força": 0.25,
            "bloqueio e entrega": 0.25,
            "aproximação": 0.15,
        },
        maturity="experimental",
        min_repetitions=3,
        risks=[
            "Rotação contínua no disco e no martelo invalida o pressuposto de plano fixo em captura monocular.",
            "Ângulo e velocidade de largada exigem tracking do engenho e calibração — ainda não implementados.",
            "240 fps é o mínimo para a fase de largada; abaixo disso as métricas temporais não são interpretáveis.",
            "Posicionar câmaras fora dos sectores de queda.",
        ],
    )
)
