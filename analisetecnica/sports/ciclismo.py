"""Perfil de ciclismo. Ver docs/sports/ciclismo.md.

Primeiro perfil a implementar: câmara fixa, movimento planar e perpendicular à
câmara, repetição indefinida. É o ambiente mais favorável para validar o
pipeline completo.
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
from ..core.profile import ReferenceSet, SportProfile, ViewSpec, register
from ..core.segmentation import CyclicSegmenter
from ..core.types import Band, Laterality, Plane, Requires, Side, View
from . import _common as C


def _segmenter() -> CyclicSegmenter:
    # Ponto morto superior: altura máxima do tornozelo (y mínimo na imagem).
    return CyclicSegmenter(
        signal=lambda fr: fr.get("right_ankle").y if fr.get("right_ankle") else float("nan"),
        cycle_event="crank_tdc",
        kind="min",
        min_separation=12,
        phase_variable="crank_angle",
    )


def _rom_symmetry(view: View, a: str, b: str, c: str):
    """Diferença de amplitude articular entre lados."""

    def compute(ctx: MetricContext) -> list[float]:
        original = ctx.side
        per_side = {}
        for side in (Side.LEFT, Side.RIGHT):
            ctx.side = side
            per_side[side] = [
                C.amplitude(C.joint_angle_series(ctx, seg, view, a, b, c))
                for seg in ctx.segments
            ]
        ctx.side = original
        out = []
        for l, r in zip(per_side[Side.LEFT], per_side[Side.RIGHT]):
            if l == l and r == r:
                out.append(abs(l - r))
        return out

    return compute


def _cadence_rpm():
    def compute(ctx: MetricContext) -> list[float]:
        fps = ctx.fps
        if not fps:
            return []
        return [
            60.0 * fps / (seg.end - seg.start)
            for seg in ctx.segments
            if seg.end > seg.start
        ]

    return compute


LATERAL, FRONTAL, POSTERIOR = View.LATERAL, View.FRONTAL, View.POSTERIOR

METRICS = [
    # -- extensão do joelho -------------------------------------------------
    MetricSpec(
        id="knee_angle_bdc",
        name="Ângulo do joelho no ponto morto inferior",
        views=[LATERAL],
        bases=["hip", "knee", "ankle"],
        compute=C.angle_at_fraction(LATERAL, "hip", "knee", "ankle", 0.5),
        target=BandTarget(138.0, 152.0, tolerance=14.0),
        unit="°",
        bilateral=True,
        weight=2.0,
        group="extensão do joelho",
        plane=Plane.SAGITTAL,
        recommendations=[
            Recommendation("below", "Joelho demasiado flectido em baixo: considerar subir o selim."),
            Recommendation("above", "Extensão excessiva em baixo: considerar descer o selim — verificar também o balanço da bacia."),
        ],
    ),
    MetricSpec(
        id="knee_angle_tdc",
        name="Ângulo do joelho no ponto morto superior",
        views=[LATERAL],
        bases=["hip", "knee", "ankle"],
        compute=C.angle_at_fraction(LATERAL, "hip", "knee", "ankle", 0.0),
        # Em cima o joelho está no máximo de flexão: ângulo interno na ordem
        # dos 65–80°, não dos 110° — a geometria manivela/perna não permite
        # simultaneamente 145° em baixo e 110° em cima.
        target=BandTarget(64.0, 82.0, tolerance=18.0),
        unit="°",
        bilateral=True,
        weight=1.0,
        group="extensão do joelho",
    ),
    MetricSpec(
        id="knee_rom",
        name="Amplitude do joelho no ciclo",
        views=[LATERAL],
        bases=["hip", "knee", "ankle"],
        compute=C.joint_angle(LATERAL, "hip", "knee", "ankle", agg=C.amplitude),
        target=BandTarget(60.0, 80.0, tolerance=20.0),
        unit="°",
        bilateral=True,
        weight=1.0,
        group="extensão do joelho",
    ),
    # -- alinhamento --------------------------------------------------------
    MetricSpec(
        id="knee_lateral_travel",
        name="Desvio lateral do joelho",
        views=[FRONTAL],
        bases=["knee", "hip"],
        compute=C.lateral_excursion(FRONTAL, "knee", "hip", scale="femur"),
        target=MinimizeTarget(0.06, 0.22),
        unit="ratio",
        bilateral=True,
        weight=1.0,
        group="alinhamento do joelho",
        plane=Plane.FRONTAL,
        recommendations=[
            Recommendation("above", "Joelho desvia medial-lateralmente: rever posição da chaveta, largura do eixo e mobilidade da anca."),
        ],
    ),
    # -- bacia ---------------------------------------------------------------
    MetricSpec(
        id="pelvic_rock",
        name="Balanço da bacia no selim",
        views=[POSTERIOR],
        bases=["hip"],
        compute=C.bilateral_height_difference(POSTERIOR, "hip", scale="hip"),
        target=MinimizeTarget(0.05, 0.25),
        unit="ratio",
        weight=1.0,
        group="estabilidade da bacia",
        plane=Plane.FRONTAL,
        recommendations=[
            Recommendation("above", "Bacia balança no selim: indício de selim alto — cruzar com o ângulo do joelho em baixo."),
        ],
    ),
    # -- tronco e membros superiores ----------------------------------------
    MetricSpec(
        id="trunk_angle",
        name="Inclinação do tronco",
        views=[LATERAL],
        bases=["hip", "shoulder"],
        compute=C.segment_to_horizontal(LATERAL, "hip", "shoulder"),
        target=BandTarget(28.0, 45.0, tolerance=18.0),
        unit="°",
        weight=1.5,
        group="tronco e pescoço",
        recommendations=[
            Recommendation("above", "Tronco muito erguido: perde aerodinâmica; avaliar avanço e queda do guiador."),
            Recommendation("below", "Tronco muito baixo: verificar tolerância lombar e abertura da anca."),
        ],
    ),
    MetricSpec(
        id="elbow_angle",
        name="Ângulo do cotovelo",
        views=[LATERAL],
        bases=["shoulder", "elbow", "wrist"],
        compute=C.joint_angle(LATERAL, "shoulder", "elbow", "wrist"),
        target=BandTarget(140.0, 165.0, tolerance=20.0),
        unit="°",
        weight=1.0,
        group="tronco e pescoço",
        recommendations=[
            Recommendation("above", "Braço demasiado esticado: absorve mal a vibração; encurtar o avanço."),
        ],
    ),
    MetricSpec(
        id="neck_extension",
        name="Extensão cervical",
        views=[LATERAL],
        bases=["shoulder", "ear", "nose"],
        compute=C.joint_angle(LATERAL, "shoulder", "ear", "nose"),
        target=BandTarget(95.0, 145.0, tolerance=35.0),
        unit="°",
        weight=0.8,
        group="tronco e pescoço",
    ),
    # -- simetria ------------------------------------------------------------
    MetricSpec(
        id="knee_rom_symmetry",
        name="Simetria da amplitude do joelho",
        views=[LATERAL],
        bases=["hip", "knee", "ankle"],
        compute=_rom_symmetry(LATERAL, "hip", "knee", "ankle"),
        target=MinimizeTarget(2.0, 12.0),
        unit="°",
        weight=1.0,
        group="simetria",
        caveat=(
            "Numa única câmara lateral o membro afastado é ocluído; simetria "
            "fiável exige duas câmaras sincronizadas."
        ),
    ),
    MetricSpec(
        id="cadence",
        name="Cadência",
        views=[LATERAL],
        bases=["ankle"],
        compute=_cadence_rpm(),
        target=BandTarget(80.0, 100.0, tolerance=25.0),
        unit="rpm",
        requires=Requires.FPS,
        min_fps=30,
        weight=1.0,
        group="simetria",
    ),
]


PROFILE = register(
    SportProfile(
        id="ciclismo",
        name="Ciclismo",
        views=[
            ViewSpec(LATERAL, required=True, laterality=Laterality.DIRECT, plane=Plane.SAGITTAL,
                     purpose="ângulos articulares, tronco, posição sobre a bicicleta"),
            ViewSpec(FRONTAL, required=False, laterality=Laterality.DIRECT, plane=Plane.FRONTAL,
                     purpose="desvio medial-lateral do joelho"),
            ViewSpec(POSTERIOR, required=False, laterality=Laterality.MIRRORED, plane=Plane.FRONTAL,
                     purpose="balanço da bacia"),
        ],
        segmenter=_segmenter,
        metrics=METRICS,
        filter_spec=FilterSpec(
            confidence_threshold=0.5,
            gap_interpolation="spline",
            max_gap_frames=4,
            smoothing="butterworth",
            order=4,
            cutoff_hz=6.0,
        ),
        group_weights={
            "extensão do joelho": 0.30,
            "alinhamento do joelho": 0.20,
            "estabilidade da bacia": 0.15,
            "tronco e pescoço": 0.20,
            "simetria": 0.15,
        },
        references=[
            ReferenceSet(
                id="ciclismo_estrada_banda",
                kind="elite_band",
                event="estrada",
                bands={
                    "knee_angle_bdc": Band(145.0, 5.0, samples=12),
                    "knee_angle_tdc": Band(109.0, 6.0, samples=12),
                    "trunk_angle": Band(36.0, 6.0, samples=12),
                    "cadence": Band(90.0, 8.0, samples=12),
                },
            )
        ],
        maturity="stable",
        min_repetitions=5,
        risks=[
            "O membro afastado é ocluído na vista lateral — simetria pede duas câmaras.",
            "Quadro e roda podem induzir keypoints falsos; usar fundo contrastante.",
            "Os keypoints do pé são os menos estáveis: ler o ângulo do tornozelo com reserva.",
        ],
    )
)
