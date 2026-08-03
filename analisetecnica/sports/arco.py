"""Perfil de tiro com arco recurvo. Ver docs/sports/tiro-com-arco.md.

Duas diferenças estruturais face aos perfis cíclicos:

- postura deliberadamente assimétrica → `bilateral=False` em tudo;
- a precisão exigida é de escala inferior ao ruído da pose 2D → o que se mede é
  a **repetibilidade entre tiros**, não valores absolutos de um tiro isolado.

Métricas que dependem do arco (deriva da mira, alinhamento da corda) exigem o
subsistema de tracking de objectos e ainda não estão implementadas.
"""

from __future__ import annotations

import math

from ..core.filtering import FilterSpec
from ..core.geometry import angle, angle_to_vertical, distance, midpoint
from ..core.metrics import (
    BandTarget,
    ConsistencyTarget,
    MetricContext,
    MetricSpec,
    MinimizeTarget,
    Recommendation,
)
from ..core.profile import SportProfile, ViewSpec, register
from ..core.segmentation import PhaseSegmenter
from ..core.types import Laterality, Plane, PoseSequence, Side, View
from . import _common as C

POSTERIOR = View.POSTERIOR

# Atirador destro: braço do arco à esquerda, braço de tracção à direita.
BOW_SIDE, DRAW_SIDE = Side.LEFT, Side.RIGHT


def _draw_length_signal(seq: PoseSequence) -> list[float]:
    """Distância entre os punhos — cresce na tracção, colapsa na largada.

    Independente de rótulos de lateralidade, por isso serve de detector de
    evento mesmo antes de qualquer correcção de vista.
    """
    out = []
    for fr in seq.frames:
        a, b = fr.get("left_wrist"), fr.get("right_wrist")
        out.append(distance(a, b) if a and b else float("nan"))
    return out


def _release_detector(seq: PoseSequence) -> list[int]:
    """Largada: queda abrupta do comprimento de tracção.

    É o evento mais fiável do gesto e serve de âncora temporal para as
    restantes fases.
    """
    sig = _draw_length_signal(seq)
    n = len(sig)
    if n < 8:
        return []
    deriv = [0.0] * n
    for i in range(1, n - 1):
        if sig[i - 1] == sig[i - 1] and sig[i + 1] == sig[i + 1]:
            deriv[i] = (sig[i + 1] - sig[i - 1]) / 2.0

    drops = [d for d in deriv if d < 0]
    if not drops:
        return []
    drops.sort()
    threshold = drops[max(0, int(0.02 * len(drops)))] * 0.6
    if threshold >= 0:
        return []

    events, last = [], -10**9
    for i, d in enumerate(deriv):
        if d <= threshold and i - last > n // 40 + 5:
            events.append(i)
            last = i
    return events


def _segmenter() -> PhaseSegmenter:
    return PhaseSegmenter(
        phases=["stance", "setup", "draw", "anchor", "expansion", "release"],
        anchor_event="release",
        anchor_detector=_release_detector,
        pre_frames=300,
        post_frames=20,
        repetition_label="shot",
    )


def _frame_at(ctx: MetricContext, seg, fraction: float):
    idx = seg.start + int(round((seg.end - seg.start) * fraction))
    return ctx.frame(POSTERIOR, idx)


def _head_width(ctx: MetricContext) -> float:
    def f(fr):
        a, b = fr.get("left_ear"), fr.get("right_ear")
        return distance(a, b) if a and b else None

    return ctx._median_over_frames(POSTERIOR, f)


def _per_shot(fn, fraction: float = 0.72):
    def compute(ctx: MetricContext) -> list[float]:
        out = []
        for seg in ctx.segments:
            fr = _frame_at(ctx, seg, fraction)
            if fr is None:
                continue
            try:
                v = fn(ctx, fr)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                v = float("nan")
            if v is not None and v == v:
                out.append(v)
        return out

    return compute


def _bow_arm_extension(ctx: MetricContext, fr) -> float:
    pts = [
        ctx.kp(fr, b, POSTERIOR, BOW_SIDE) for b in ("shoulder", "elbow", "wrist")
    ]
    return angle(*pts) if all(pts) else float("nan")


def _bow_shoulder_height(ctx: MetricContext, fr) -> float:
    norm = ctx.shoulder_width(POSTERIOR)
    bow = ctx.kp(fr, "shoulder", POSTERIOR, BOW_SIDE)
    draw = ctx.kp(fr, "shoulder", POSTERIOR, DRAW_SIDE)
    if not (bow and draw) or not norm or norm != norm:
        return float("nan")
    return (bow.height - draw.height) / norm


def _spine_vertical(ctx: MetricContext, fr) -> float:
    lh, rh = fr.get("left_hip"), fr.get("right_hip")
    ls, rs = fr.get("left_shoulder"), fr.get("right_shoulder")
    if not all((lh, rh, ls, rs)):
        return float("nan")
    return abs(angle_to_vertical(midpoint(lh, rh), midpoint(ls, rs)))


def _head_tilt(ctx: MetricContext, fr) -> float:
    ls, rs, nose = fr.get("left_shoulder"), fr.get("right_shoulder"), fr.get("nose")
    if not all((ls, rs, nose)):
        return float("nan")
    return abs(angle_to_vertical(midpoint(ls, rs), nose))


def _stance_width(ctx: MetricContext, fr) -> float:
    norm = ctx.shoulder_width(POSTERIOR)
    la, ra = fr.get("left_ankle"), fr.get("right_ankle")
    if not (la and ra) or not norm or norm != norm:
        return float("nan")
    return distance(la, ra) / norm


def _anchor_distance(ctx: MetricContext, fr) -> float:
    """Mão de tracção ↔ referência facial, normalizada pela largura da cabeça."""
    norm = _head_width(ctx)
    wrist = ctx.kp(fr, "wrist", POSTERIOR, DRAW_SIDE)
    ear = ctx.kp(fr, "ear", POSTERIOR, DRAW_SIDE)
    if not (wrist and ear) or not norm or norm != norm or norm == 0:
        return float("nan")
    return distance(wrist, ear) / norm


def _draw_length(ctx: MetricContext, fr) -> float:
    norm = ctx.shoulder_width(POSTERIOR)
    bow = ctx.kp(fr, "wrist", POSTERIOR, BOW_SIDE)
    draw = ctx.kp(fr, "wrist", POSTERIOR, DRAW_SIDE)
    if not (bow and draw) or not norm or norm != norm:
        return float("nan")
    return distance(bow, draw) / norm


def _bow_hand_stability():
    """Tremor da mão do arco na janela de mira, **sobre o sinal não filtrado**."""

    def compute(ctx: MetricContext) -> list[float]:
        norm = ctx.shoulder_width(POSTERIOR)
        if not norm or norm != norm:
            return []
        raw = ctx.seq(POSTERIOR, raw=True)
        out = []
        for seg in ctx.segments:
            span = seg.end - seg.start
            lo = seg.start + int(span * 0.45)
            hi = seg.start + int(span * 0.92)
            xs, ys = [], []
            for i in range(max(0, lo), min(hi, len(raw.frames))):
                p = ctx.kp(raw.frames[i], "wrist", POSTERIOR, BOW_SIDE)
                if p:
                    xs.append(p.x)
                    ys.append(p.y)
            if len(xs) < 5:
                continue
            out.append(math.hypot(C._sd(xs), C._sd(ys)) / norm)
        return out

    return compute


METRICS = [
    # -- repetibilidade: o núcleo do perfil ---------------------------------
    MetricSpec(
        id="anchor_consistency",
        name="Consistência do ponto de âncora",
        views=[POSTERIOR],
        bases=["wrist", "ear"],
        compute=_per_shot(_anchor_distance),
        target=ConsistencyTarget(good_cv=0.03, bad_cv=0.18),
        unit="cv",
        weight=2.0,
        group="repetibilidade",
        recommendations=[
            Recommendation("inconsistent", "Âncora varia entre flechas: fixar referência facial única e verificá-la em espelho antes de cada tiro."),
        ],
    ),
    MetricSpec(
        id="draw_length_consistency",
        name="Consistência do comprimento de tracção",
        views=[POSTERIOR],
        bases=["wrist"],
        compute=_per_shot(_draw_length),
        target=ConsistencyTarget(good_cv=0.02, bad_cv=0.12),
        unit="cv",
        weight=1.5,
        group="repetibilidade",
        recommendations=[
            Recommendation("inconsistent", "Tracção com comprimento variável: trabalhar expansão até ao clicker de forma consistente."),
        ],
    ),
    MetricSpec(
        id="posture_repeatability",
        name="Repetibilidade da postura dos ombros",
        views=[POSTERIOR],
        bases=["shoulder"],
        compute=_per_shot(_bow_shoulder_height),
        # Base em desvio-padrão e não em coeficiente de variação: a altura
        # relativa dos ombros passa por zero, e aí o cv explode.
        target=ConsistencyTarget(good_cv=0.02, bad_cv=0.12, basis="sd"),
        unit="sd",
        weight=1.5,
        group="repetibilidade",
    ),
    # -- alinhamento e postura ----------------------------------------------
    MetricSpec(
        id="bow_shoulder_height",
        name="Altura do ombro do arco",
        views=[POSTERIOR],
        bases=["shoulder"],
        compute=_per_shot(_bow_shoulder_height),
        target=BandTarget(-0.10, 0.06, tolerance=0.14),
        unit="ratio",
        weight=1.5,
        group="postura",
        recommendations=[
            Recommendation("above", "Ombro do arco sobe na tracção: baixar e fixar antes de iniciar a puxada."),
        ],
    ),
    MetricSpec(
        id="spine_vertical",
        name="Verticalidade do tronco",
        views=[POSTERIOR],
        bases=["hip", "shoulder"],
        compute=_per_shot(_spine_vertical),
        target=MinimizeTarget(3.0, 14.0),
        unit="°",
        weight=1.5,
        group="postura",
        recommendations=[
            Recommendation("above", "Inclinação do tronco para trás: compensação do peso do arco — reforçar o core e rever a distribuição do peso."),
        ],
    ),
    MetricSpec(
        id="head_tilt",
        name="Inclinação da cabeça",
        views=[POSTERIOR],
        bases=["shoulder", "nose"],
        compute=_per_shot(_head_tilt),
        target=MinimizeTarget(4.0, 16.0),
        unit="°",
        weight=1.0,
        group="postura",
    ),
    MetricSpec(
        id="stance_width",
        name="Abertura da base",
        views=[POSTERIOR],
        bases=["ankle"],
        compute=_per_shot(_stance_width),
        target=BandTarget(0.80, 1.25, tolerance=0.40),
        unit="ratio",
        weight=1.0,
        group="postura",
    ),
    MetricSpec(
        id="bow_arm_extension",
        name="Extensão do braço do arco",
        views=[POSTERIOR],
        bases=["shoulder", "elbow", "wrist"],
        compute=_per_shot(_bow_arm_extension),
        target=BandTarget(160.0, 176.0, tolerance=16.0),
        unit="°",
        weight=1.5,
        group="alinhamento",
        recommendations=[
            Recommendation("below", "Braço do arco demasiado flectido: perde estrutura sob carga."),
            Recommendation("above", "Cotovelo bloqueado em hiperextensão: expõe o braço à passagem da corda."),
        ],
    ),
    # -- estabilidade --------------------------------------------------------
    MetricSpec(
        id="bow_hand_stability",
        name="Estabilidade da mão do arco",
        views=[POSTERIOR],
        bases=["wrist"],
        compute=_bow_hand_stability(),
        target=MinimizeTarget(0.012, 0.075),
        unit="ratio",
        weight=2.0,
        group="estabilidade",
        uses_raw_signal=True,
        caveat="Calculada sobre o sinal antes da suavização — filtrar removeria o tremor que se pretende medir.",
        recommendations=[
            Recommendation("above", "Tremor elevado na fase de mira: rever resistência específica e tempo total de manutenção."),
        ],
    ),
]


PROFILE = register(
    SportProfile(
        id="arco",
        name="Tiro com arco recurvo",
        views=[
            ViewSpec(POSTERIOR, required=True, laterality=Laterality.MIRRORED, plane=Plane.FRONTAL,
                     purpose="postura, altura dos ombros, âncora, verticalidade"),
            ViewSpec(View.SUPERIOR, required=False, laterality=Laterality.DIRECT, plane=Plane.TRANSVERSE,
                     purpose="alinhamento da linha de ombros e do antebraço de tracção"),
            ViewSpec(View.LATERAL, required=False, laterality=Laterality.DIRECT, plane=Plane.SAGITTAL,
                     purpose="inclinação do tronco, extensão do braço do arco"),
        ],
        segmenter=_segmenter,
        metrics=METRICS,
        filter_spec=FilterSpec(
            confidence_threshold=0.6,
            gap_interpolation="linear",
            max_gap_frames=2,
            smoothing="butterworth",
            order=2,
            cutoff_hz=3.0,
        ),
        group_weights={
            "repetibilidade": 0.40,
            "alinhamento": 0.25,
            "postura": 0.20,
            "estabilidade": 0.15,
        },
        maturity="beta",
        min_repetitions=6,
        risks=[
            "Vista superior está fora da distribuição de treino do MediaPipe — validar com vídeo real; plano B é anotação assistida.",
            "Métricas dependentes do arco (deriva da mira, alinhamento da corda) exigem tracking de objectos, ainda não implementado.",
            "Uma análise de tiro único não é interpretável: o perfil exige uma série.",
        ],
    )
)
