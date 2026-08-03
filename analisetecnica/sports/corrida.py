"""Perfil de atletismo — corrida. Ver docs/sports/atletismo-corrida.md.

Definições, porque a ambiguidade aqui contamina metade das métricas:
passada = contacto de um pé ao contacto seguinte do **mesmo** pé; passo = de um
pé ao outro. A cadência é reportada em **passos/min** ≈ 2 × passadas/min.
"""

from __future__ import annotations

from ..core.filtering import FilterSpec
from ..core.metrics import (
    BandTarget,
    MatchReferenceTarget,
    MetricContext,
    MetricSpec,
    MinimizeTarget,
    Recommendation,
)
from ..core.profile import ReferenceSet, SportProfile, ViewSpec, register
from ..core.segmentation import CyclicSegmenter
from ..core.types import Band, Laterality, Plane, Requires, Side, View
from . import _common as C

LATERAL, FRONTAL, POSTERIOR = View.LATERAL, View.FRONTAL, View.POSTERIOR


def _segmenter() -> CyclicSegmenter:
    # Contacto do pé direito: ponto mais baixo do tornozelo (y máximo).
    return CyclicSegmenter(
        signal=lambda fr: fr.get("right_ankle").y if fr.get("right_ankle") else float("nan"),
        cycle_event="footstrike_right",
        kind="max",
        min_separation=25,
    )


def _symmetry_of(compute_side):
    """Diferença absoluta entre lados, normalizada pela média."""

    def compute(ctx: MetricContext) -> list[float]:
        original = ctx.side
        vals = {}
        for side in (Side.LEFT, Side.RIGHT):
            ctx.side = side
            vals[side] = compute_side(ctx)
        ctx.side = original
        l, r = vals[Side.LEFT], vals[Side.RIGHT]
        if not l or not r:
            return []
        ml = sum(l) / len(l)
        mr = sum(r) / len(r)
        base = (ml + mr) / 2
        if base == 0:
            return []
        return [abs(ml - mr) / abs(base)]

    return compute


METRICS = [
    # -- mecânica dos membros inferiores ------------------------------------
    MetricSpec(
        id="knee_lift_height",
        name="Elevação do joelho",
        views=[LATERAL],
        bases=["knee", "hip"],
        compute=C.normalized_height_above(LATERAL, "knee", "hip", scale="leg"),
        # Mesmo em velocistas o joelho chega aproximadamente à altura da anca,
        # não acima: a banda é centrada ligeiramente abaixo de zero.
        target=BandTarget(-0.12, 0.05, tolerance=0.15),
        unit="ratio",
        bilateral=True,
        weight=2.0,
        group="membros inferiores",
        recommendations=[
            Recommendation("below", "Elevação do joelho baixa: trabalhar skipping alto e força do flexor da anca."),
            Recommendation("above", "Elevação muito alta para a prova: verificar se o padrão é adequado à distância."),
        ],
    ),
    MetricSpec(
        id="heel_recovery",
        name="Recolha do calcanhar",
        views=[LATERAL],
        bases=["heel", "hip"],
        compute=C.normalized_height_above(LATERAL, "heel", "hip", scale="leg"),
        target=BandTarget(-0.35, -0.05, tolerance=0.25),
        unit="ratio",
        bilateral=True,
        weight=1.0,
        group="membros inferiores",
    ),
    MetricSpec(
        id="overstride",
        name="Sobrepasso no contacto",
        views=[LATERAL],
        bases=["ankle"],
        compute=C.overstride_ratio(LATERAL),
        target=MinimizeTarget(0.16, 0.45),
        unit="ratio",
        bilateral=True,
        min_fps=120,
        requires=Requires.FPS,
        weight=1.5,
        group="membros inferiores",
        recommendations=[
            Recommendation("above", "Pé pousa demasiado à frente do centro de massa: encurtar a passada e aumentar a cadência."),
        ],
    ),
    MetricSpec(
        id="knee_angle_rom",
        name="Amplitude do joelho no ciclo",
        views=[LATERAL],
        bases=["hip", "knee", "ankle"],
        compute=C.joint_angle(LATERAL, "hip", "knee", "ankle", agg=C.amplitude),
        target=MatchReferenceTarget(),
        unit="°",
        bilateral=True,
        weight=1.0,
        group="membros inferiores",
    ),
    # -- contacto e apoio do pé ---------------------------------------------
    MetricSpec(
        id="ground_contact_time",
        name="Tempo de contacto no solo",
        views=[LATERAL],
        bases=["heel", "foot_index"],
        compute=C.contact_time_ms(LATERAL),
        target=MinimizeTarget(200.0, 380.0),
        unit="ms",
        bilateral=True,
        requires=Requires.FPS,
        min_fps=120,
        weight=2.0,
        group="contacto e apoio",
        caveat=(
            "Deteção de contacto é o ponto mais frágil do pipeline; rever os "
            "eventos manualmente antes de decidir treino com base neste valor."
        ),
        recommendations=[
            Recommendation("above", "Contacto longo: trabalhar rigidez do tornozelo e reactividade (pliometria)."),
        ],
    ),
    MetricSpec(
        id="flight_time",
        name="Tempo de voo (ambos os pés no ar)",
        views=[LATERAL],
        bases=["heel", "foot_index"],
        compute=C.flight_time_ms(LATERAL),
        target=MatchReferenceTarget(),
        unit="ms",
        bilateral=False,
        requires=Requires.FPS,
        min_fps=120,
        weight=1.0,
        group="contacto e apoio",
    ),
    MetricSpec(
        id="foot_strike_index",
        name="Tipo de apoio do pé",
        views=[LATERAL],
        bases=["heel", "foot_index"],
        compute=C.strike_index(LATERAL),
        target=BandTarget(-0.10, 0.25, tolerance=0.30),
        unit="ratio",
        bilateral=True,
        requires=Requires.FPS,
        min_fps=120,
        weight=1.5,
        group="contacto e apoio",
        recommendations=[
            Recommendation("below", "Ataque de calcanhar marcado: aproximar o apoio do médio-pé, aumentando a cadência."),
        ],
    ),
    MetricSpec(
        id="foot_contact_angle",
        name="Ângulo do pé no contacto",
        views=[LATERAL],
        bases=["knee", "ankle", "foot_index"],
        compute=C.foot_angle_at_strike(LATERAL),
        target=BandTarget(75.0, 115.0, tolerance=25.0),
        unit="°",
        bilateral=True,
        requires=Requires.FPS,
        min_fps=120,
        weight=1.5,
        group="contacto e apoio",
    ),
    MetricSpec(
        id="cadence",
        name="Cadência",
        views=[LATERAL],
        bases=["ankle"],
        compute=C.cadence_steps_per_min(LATERAL),
        target=BandTarget(165.0, 195.0, tolerance=25.0),
        unit="passos/min",
        requires=Requires.FPS,
        min_fps=60,
        weight=1.0,
        group="contacto e apoio",
    ),
    # -- tronco e bacia ------------------------------------------------------
    MetricSpec(
        id="trunk_lean",
        name="Inclinação do tronco",
        views=[LATERAL],
        bases=["hip", "shoulder"],
        compute=C.trunk_to_vertical(LATERAL),
        target=BandTarget(4.0, 12.0, tolerance=8.0),
        unit="°",
        weight=1.5,
        group="tronco e bacia",
        recommendations=[
            Recommendation("above", "Tronco muito inclinado: soltar a anca e evitar flectir a partir da cintura."),
            Recommendation("below", "Tronco demasiado vertical: procurar ligeira inclinação a partir do tornozelo."),
        ],
    ),
    MetricSpec(
        id="pelvic_drop",
        name="Queda da anca",
        views=[FRONTAL],
        bases=["hip"],
        compute=C.bilateral_height_difference(FRONTAL, "hip", scale="hip"),
        target=MinimizeTarget(0.06, 0.28),
        unit="ratio",
        weight=1.5,
        group="tronco e bacia",
        plane=Plane.FRONTAL,
        recommendations=[
            Recommendation("above", "Queda da anca acentuada: reforçar abdutores e glúteo médio em apoio unipodal."),
        ],
    ),
    MetricSpec(
        id="vertical_oscillation",
        name="Oscilação vertical do centro de massa",
        views=[LATERAL],
        bases=["shoulder", "hip"],
        compute=C.com_vertical_oscillation(LATERAL),
        target=MinimizeTarget(0.035, 0.11),
        unit="ratio",
        weight=1.0,
        group="tronco e bacia",
    ),
    # -- membros superiores --------------------------------------------------
    MetricSpec(
        id="elbow_angle",
        name="Ângulo do cotovelo",
        views=[LATERAL],
        bases=["shoulder", "elbow", "wrist"],
        compute=C.joint_angle(LATERAL, "shoulder", "elbow", "wrist"),
        target=BandTarget(70.0, 110.0, tolerance=30.0),
        unit="°",
        bilateral=True,
        weight=1.0,
        group="membros superiores",
    ),
    MetricSpec(
        id="shoulder_rom",
        name="Amplitude do braço",
        views=[LATERAL],
        bases=["hip", "shoulder", "elbow"],
        compute=C.joint_angle(LATERAL, "hip", "shoulder", "elbow", agg=C.amplitude),
        target=BandTarget(35.0, 75.0, tolerance=25.0),
        unit="°",
        bilateral=True,
        weight=1.0,
        group="membros superiores",
    ),
    MetricSpec(
        id="arm_crossover",
        name="Cruzamento do braço na linha média",
        views=[FRONTAL],
        bases=["wrist", "shoulder"],
        compute=C.lateral_excursion(FRONTAL, "wrist", "shoulder", scale="shoulder"),
        target=MinimizeTarget(0.25, 0.70),
        unit="ratio",
        bilateral=True,
        weight=1.0,
        group="membros superiores",
        plane=Plane.FRONTAL,
        recommendations=[
            Recommendation("above", "Braço cruza a linha média: induz rotação do tronco e desperdiça energia."),
        ],
    ),
    # -- simetria ------------------------------------------------------------
    MetricSpec(
        id="contact_time_symmetry",
        name="Simetria do tempo de contacto",
        views=[LATERAL],
        bases=["heel", "foot_index"],
        compute=_symmetry_of(C.contact_time_ms(LATERAL)),
        target=MinimizeTarget(0.04, 0.20),
        unit="ratio",
        requires=Requires.FPS,
        min_fps=120,
        weight=2.0,
        group="simetria",
        caveat="Vista lateral única oclui o membro afastado; ler com reserva.",
        recommendations=[
            Recommendation("above", "Assimetria de apoio: investigar história de lesão e diferença de força entre membros."),
        ],
    ),
    MetricSpec(
        id="knee_lift_symmetry",
        name="Simetria da elevação do joelho",
        views=[LATERAL],
        bases=["knee", "hip"],
        compute=_symmetry_of(C.normalized_height_above(LATERAL, "knee", "hip", scale="leg")),
        target=MinimizeTarget(0.08, 0.35),
        unit="ratio",
        weight=1.0,
        group="simetria",
    ),
]


PROFILE = register(
    SportProfile(
        id="corrida",
        name="Atletismo — corrida",
        views=[
            ViewSpec(LATERAL, required=True, laterality=Laterality.DIRECT, plane=Plane.SAGITTAL,
                     purpose="ângulos articulares, tronco, contacto no solo, apoio do pé"),
            ViewSpec(FRONTAL, required=False, laterality=Laterality.DIRECT, plane=Plane.FRONTAL,
                     purpose="queda da anca, cruzamento de braços"),
            ViewSpec(POSTERIOR, required=False, laterality=Laterality.MIRRORED, plane=Plane.FRONTAL,
                     purpose="queda da anca, pronação, simetria"),
        ],
        segmenter=_segmenter,
        metrics=METRICS,
        filter_spec=FilterSpec(
            confidence_threshold=0.5,
            gap_interpolation="spline",
            max_gap_frames=3,
            smoothing="butterworth",
            order=4,
            cutoff_hz=10.0,
        ),
        group_weights={
            "membros inferiores": 0.25,
            "contacto e apoio": 0.25,
            "tronco e bacia": 0.25,
            "membros superiores": 0.10,
            "simetria": 0.15,
        },
        references=[
            ReferenceSet(
                id="corrida_meio_fundo_banda",
                kind="elite_band",
                event="meio-fundo",
                bands={
                    "knee_angle_rom": Band(105.0, 12.0, samples=9),
                    "flight_time": Band(130.0, 25.0, samples=9),
                    "cadence": Band(182.0, 7.0, samples=9),
                    "trunk_lean": Band(8.0, 2.5, samples=9),
                },
            )
        ],
        maturity="stable",
        min_repetitions=4,
        risks=[
            "Deteção de contacto no solo é o ponto mais frágil do pipeline — prever revisão manual.",
            "Oclusão do membro afastado na vista lateral limita a análise de simetria.",
            "Comparar sessões a ritmos diferentes invalida a evolução; registar o ritmo.",
        ],
    )
)
