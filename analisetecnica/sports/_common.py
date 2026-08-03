"""Auxiliares partilhados pelos perfis.

Vive em `sports/` e não em `core/`: são conveniências para escrever perfis, não
parte do pipeline. `core/` nunca importa daqui.
"""

from __future__ import annotations

import math
from typing import Callable

from ..core.geometry import angle, angle_to_horizontal, angle_to_vertical, distance
from ..core.metrics import MetricContext
from ..core.types import Point, Segment, Side, View

Agg = Callable[[list[float]], float]


def mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else float("nan")


def amplitude(vals: list[float]) -> float:
    return max(vals) - min(vals) if vals else float("nan")


def _finite(vals: list[float]) -> list[float]:
    return [v for v in vals if v == v]


def frames_of(ctx: MetricContext, seg: Segment, view: View):
    seq = ctx.seq(view)
    for i in range(seg.start, min(seg.end + 1, len(seq.frames))):
        yield i, seq.frames[i]


def joint_angle_series(ctx: MetricContext, seg: Segment, view: View, a: str, b: str, c: str) -> list[float]:
    out = []
    for _, fr in frames_of(ctx, seg, view):
        pts = ctx.kps(fr, view, a, b, c)
        if pts:
            out.append(angle(*pts))
    return _finite(out)


def per_cycle(
    view: View, fn: Callable[[MetricContext, Segment], float]
) -> Callable[[MetricContext], list[float]]:
    """Envolve uma função por ciclo, devolvendo uma amostra por segmento."""

    def compute(ctx: MetricContext) -> list[float]:
        out = []
        for seg in ctx.segments:
            try:
                v = fn(ctx, seg)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                v = float("nan")
            if v == v:
                out.append(v)
        return out

    return compute


def joint_angle(view: View, a: str, b: str, c: str, agg: Agg = mean):
    def fn(ctx: MetricContext, seg: Segment) -> float:
        return agg(joint_angle_series(ctx, seg, view, a, b, c))

    return per_cycle(view, fn)


def angle_at_fraction(view: View, a: str, b: str, c: str, fraction: float):
    """Ângulo num ponto específico do ciclo (0.0 = início, 0.5 = meio)."""

    def fn(ctx: MetricContext, seg: Segment) -> float:
        idx = seg.start + int(round((seg.end - seg.start) * fraction))
        fr = ctx.frame(view, idx)
        if fr is None:
            return float("nan")
        pts = ctx.kps(fr, view, a, b, c)
        return angle(*pts) if pts else float("nan")

    return per_cycle(view, fn)


def trunk_to_vertical(view: View, hip: str = "hip", shoulder: str = "shoulder"):
    def fn(ctx: MetricContext, seg: Segment) -> float:
        vals = []
        for _, fr in frames_of(ctx, seg, view):
            pts = ctx.kps(fr, view, hip, shoulder)
            if pts:
                vals.append(abs(angle_to_vertical(pts[0], pts[1])))
        return mean(_finite(vals))

    return per_cycle(view, fn)


def segment_to_horizontal(view: View, a: str, b: str):
    def fn(ctx: MetricContext, seg: Segment) -> float:
        vals = []
        for _, fr in frames_of(ctx, seg, view):
            pts = ctx.kps(fr, view, a, b)
            if pts:
                vals.append(abs(angle_to_horizontal(pts[0], pts[1])))
        return mean(_finite(vals))

    return per_cycle(view, fn)


def normalized_height_above(view: View, upper: str, lower: str, scale: str = "leg"):
    """Altura máxima de `upper` acima de `lower`, normalizada por segmento corporal.

    Métrica adimensional: dispensa calibração e é comparável entre atletas de
    estaturas diferentes.
    """

    def fn(ctx: MetricContext, seg: Segment) -> float:
        norm = _scale(ctx, view, scale)
        if not norm or norm != norm:
            return float("nan")
        best = float("-inf")
        for _, fr in frames_of(ctx, seg, view):
            pts = ctx.kps(fr, view, upper, lower)
            if pts:
                best = max(best, pts[0].height - pts[1].height)
        return best / norm if best > float("-inf") else float("nan")

    return per_cycle(view, fn)


def _scale(ctx: MetricContext, view: View, scale: str) -> float:
    return {
        "leg": ctx.leg_length,
        "femur": ctx.femur_length,
        "shoulder": ctx.shoulder_width,
        "hip": ctx.hip_width,
        "stature": ctx.stature,
    }[scale](view)


def lateral_excursion(view: View, point: str, reference: str, scale: str = "shoulder"):
    """Amplitude do desvio horizontal de um ponto face a uma referência."""

    def fn(ctx: MetricContext, seg: Segment) -> float:
        norm = _scale(ctx, view, scale)
        if not norm or norm != norm:
            return float("nan")
        vals = []
        for _, fr in frames_of(ctx, seg, view):
            pts = ctx.kps(fr, view, point, reference)
            if pts:
                vals.append((pts[0].x - pts[1].x) / norm)
        vals = _finite(vals)
        return amplitude(vals) if vals else float("nan")

    return per_cycle(view, fn)


def bilateral_height_difference(view: View, base: str, scale: str = "hip"):
    """Diferença de altura entre os lados, normalizada. Ex.: queda da anca.

    Usa desvio absoluto e não diferença percentual: sobre valores que se
    aproximam de zero a divisão explode.
    """

    def fn(ctx: MetricContext, seg: Segment) -> float:
        norm = _scale(ctx, view, scale)
        if not norm or norm != norm:
            return float("nan")
        vals = []
        for _, fr in frames_of(ctx, seg, view):
            left = ctx.kp(fr, base, view, Side.LEFT)
            right = ctx.kp(fr, base, view, Side.RIGHT)
            if left and right:
                vals.append(abs(left.height - right.height) / norm)
        vals = _finite(vals)
        return max(vals) if vals else float("nan")

    return per_cycle(view, fn)


def com_vertical_oscillation(view: View):
    def fn(ctx: MetricContext, seg: Segment) -> float:
        norm = ctx.stature(view)
        if not norm or norm != norm:
            return float("nan")
        vals = []
        for _, fr in frames_of(ctx, seg, view):
            com = ctx.center_of_mass(fr)
            if com:
                vals.append(com.height)
        vals = _finite(vals)
        return amplitude(vals) / norm if vals else float("nan")

    return per_cycle(view, fn)


# --------------------------------------------------------------------------- #
# Contacto no solo — o ponto mais frágil do pipeline
# --------------------------------------------------------------------------- #


def contact_intervals(
    ctx: MetricContext, view: View, side: Side, height_frac: float = 0.12
) -> list[tuple[int, int]]:
    """Intervalos de contacto por altura mínima do pé + velocidade horizontal baixa.

    Heurística assumidamente frágil (ver CLAUDE.md). A interface deve permitir
    revisão manual dos eventos em vez de confiar cegamente nesta deteção.
    """
    seq = ctx.seq(view)
    heights: list[float] = []
    xs: list[float] = []
    for fr in seq.frames:
        toe = ctx.kp(fr, "foot_index", view, side)
        heel = ctx.kp(fr, "heel", view, side)
        pts = [p for p in (toe, heel) if p is not None]
        if not pts:
            heights.append(float("nan"))
            xs.append(float("nan"))
            continue
        heights.append(min(p.height for p in pts))
        xs.append(sum(p.x for p in pts) / len(pts))

    valid = [h for h in heights if h == h]
    if len(valid) < 4:
        return []
    lo, hi = min(valid), max(valid)
    threshold = lo + height_frac * (hi - lo)

    speeds = [float("nan")] * len(xs)
    for i in range(1, len(xs) - 1):
        if xs[i - 1] == xs[i - 1] and xs[i + 1] == xs[i + 1]:
            speeds[i] = (xs[i + 1] - xs[i - 1]) / 2.0

    # O critério clássico é "velocidade do pé ≈ 0", mas isso só vale se a câmara
    # estiver imóvel face ao solo. Numa passadeira, ou com a câmara a acompanhar
    # o atleta, o pé em apoio move-se à velocidade do solo — não a zero. Estimar
    # essa velocidade a partir dos frames baixos torna o critério válido nos
    # três casos.
    # Estimar sobre o decil mais baixo, não sobre tudo o que passa o limiar de
    # altura: incluir a fase de aproximação ao solo inflaciona a dispersão e a
    # tolerância deixa de distinguir apoio de aproximação.
    core_threshold = lo + 0.04 * (hi - lo)
    core = [
        i for i, h in enumerate(heights)
        if h == h and h <= core_threshold and speeds[i] == speeds[i]
    ]
    if not core:
        return []
    ground_speed = _median([speeds[i] for i in core])
    deviations = [abs(speeds[i] - ground_speed) for i in core]
    scale = _median(deviations) or 0.0
    tolerance = max(3.0 * scale, 1e-4)

    raw_intervals: list[tuple[int, int]] = []
    start = None
    for i, h in enumerate(heights):
        near_ground_speed = (
            speeds[i] == speeds[i] and abs(speeds[i] - ground_speed) <= tolerance
        )
        touching = h == h and h <= threshold and near_ground_speed
        if touching and start is None:
            start = i
        elif not touching and start is not None:
            raw_intervals.append((start, i - 1))
            start = None
    if start is not None:
        raw_intervals.append((start, len(heights) - 1))

    # Um único apoio parte-se facilmente em vários intervalos por ruído nos
    # keypoints do pé — os menos estáveis do modelo. Sem esta fusão, o tempo de
    # contacto vem sistematicamente subestimado e o tempo de voo inflacionado.
    cycle_len = _cycle_length(ctx) or max(8, len(heights) // 8)
    min_gap = max(2, int(0.05 * cycle_len))
    min_len = max(2, int(0.05 * cycle_len))

    merged: list[tuple[int, int]] = []
    for a, b in raw_intervals:
        if merged and a - merged[-1][1] <= min_gap:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return [(a, b) for a, b in merged if b - a + 1 >= min_len]


def _median(vals: list[float]) -> float:
    clean = sorted(v for v in vals if v == v)
    if not clean:
        return float("nan")
    return clean[len(clean) // 2]


def _cycle_length(ctx: MetricContext) -> int:
    spans = [seg.end - seg.start for seg in ctx.segments if seg.end > seg.start]
    if not spans:
        return 0
    spans.sort()
    return spans[len(spans) // 2]


def contact_time_ms(view: View):
    def compute(ctx: MetricContext) -> list[float]:
        fps = ctx.fps
        if not fps:
            return []
        out = []
        for a, b in contact_intervals(ctx, view, ctx.side or Side.RIGHT):
            out.append(1000.0 * (b - a + 1) / fps)
        return out

    return compute


def flight_time_ms(view: View):
    """Tempo com **ambos** os pés fora do solo.

    Não confundir com o tempo de balanço de um pé: o intervalo entre contactos
    consecutivos do mesmo pé inclui o apoio do pé contrário, e é quase o dobro.
    """

    def compute(ctx: MetricContext) -> list[float]:
        fps = ctx.fps
        if not fps:
            return []
        n = len(ctx.seq(view).frames)
        grounded = [False] * n
        for side in (Side.LEFT, Side.RIGHT):
            for a, b in contact_intervals(ctx, view, side):
                for i in range(a, min(b + 1, n)):
                    grounded[i] = True

        out: list[float] = []
        start = None
        for i, g in enumerate(grounded):
            if not g and start is None:
                start = i
            elif g and start is not None:
                # Descartar a primeira e a última janela: podem estar truncadas
                # pelo início ou fim da gravação.
                if start > 0:
                    out.append(1000.0 * (i - start) / fps)
                start = None
        return out

    return compute


def strike_index(view: View):
    """Posição relativa do calcanhar face à ponta no primeiro contacto.

    Negativo = calcanhar mais baixo (ataque de calcanhar); perto de zero =
    médio; positivo = antepé.
    """

    def compute(ctx: MetricContext) -> list[float]:
        side = ctx.side or Side.RIGHT
        out = []
        for a, _ in contact_intervals(ctx, view, side):
            fr = ctx.frame(view, a)
            if fr is None:
                continue
            heel = ctx.kp(fr, "heel", view, side)
            toe = ctx.kp(fr, "foot_index", view, side)
            if not (heel and toe):
                continue
            norm = distance(heel, toe)
            if norm <= 0:
                continue
            out.append((heel.height - toe.height) / norm)
        return out

    return compute


def foot_angle_at_strike(view: View):
    def compute(ctx: MetricContext) -> list[float]:
        side = ctx.side or Side.RIGHT
        out = []
        for a, _ in contact_intervals(ctx, view, side):
            fr = ctx.frame(view, a)
            if fr is None:
                continue
            pts = ctx.kps(fr, view, "knee", "ankle", "foot_index")
            if pts:
                out.append(angle(*pts))
        return out

    return compute


def cadence_steps_per_min(view: View):
    """Cadência em **passos** por minuto (≈ 2 × passadas/min).

    A unidade é explícita para evitar o erro de factor 2 entre passo e passada.
    """

    def compute(ctx: MetricContext) -> list[float]:
        fps = ctx.fps
        if not fps or not ctx.segments:
            return []
        out = []
        for seg in ctx.segments:
            span = seg.end - seg.start
            if span <= 0:
                continue
            stride_s = span / fps
            out.append(2.0 * 60.0 / stride_s)
        return out

    return compute


def overstride_ratio(view: View):
    def compute(ctx: MetricContext) -> list[float]:
        side = ctx.side or Side.RIGHT
        norm = ctx.leg_length(view)
        if not norm or norm != norm:
            return []
        out = []
        for a, _ in contact_intervals(ctx, view, side):
            fr = ctx.frame(view, a)
            if fr is None:
                continue
            ankle = ctx.kp(fr, "ankle", view, side)
            com = ctx.center_of_mass(fr)
            if ankle and com:
                out.append(abs(ankle.x - com.x) / norm)
        return out

    return compute


# --------------------------------------------------------------------------- #
# Estabilidade — calculada sobre o sinal cru
# --------------------------------------------------------------------------- #


def tremor_amplitude(view: View, base: str, scale: str = "shoulder", window: tuple[float, float] = (0.35, 0.85)):
    """Amplitude do tremor numa janela do segmento, **sobre o sinal não filtrado**.

    Suavizar antes removeria exactamente o que se pretende medir.
    """

    def compute(ctx: MetricContext) -> list[float]:
        norm = _scale(ctx, view, scale)
        if not norm or norm != norm:
            return []
        raw = ctx.seq(view, raw=True)
        out = []
        for seg in ctx.segments:
            span = seg.end - seg.start
            lo = seg.start + int(span * window[0])
            hi = seg.start + int(span * window[1])
            xs, ys = [], []
            for i in range(lo, min(hi, len(raw.frames))):
                p = ctx.kp(raw.frames[i], base, view)
                if p:
                    xs.append(p.x)
                    ys.append(p.y)
            if len(xs) < 4:
                continue
            sx = _sd(xs)
            sy = _sd(ys)
            out.append(math.hypot(sx, sy) / norm)
        return out

    return compute


def _sd(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


def normalized_distance(view: View, a: str, b: str, scale: str = "shoulder", at_fraction: float = 0.6):
    """Distância adimensional entre dois pontos, num instante do segmento."""

    def fn(ctx: MetricContext, seg: Segment) -> float:
        norm = _scale(ctx, view, scale)
        if not norm or norm != norm:
            return float("nan")
        idx = seg.start + int(round((seg.end - seg.start) * at_fraction))
        fr = ctx.frame(view, idx)
        if fr is None:
            return float("nan")
        pts = ctx.kps(fr, view, a, b)
        return distance(*pts) / norm if pts else float("nan")

    return per_cycle(view, fn)


def signed_height_difference(view: View, upper: str, lower: str, scale: str = "shoulder", at_fraction: float = 0.6):
    def fn(ctx: MetricContext, seg: Segment) -> float:
        norm = _scale(ctx, view, scale)
        if not norm or norm != norm:
            return float("nan")
        idx = seg.start + int(round((seg.end - seg.start) * at_fraction))
        fr = ctx.frame(view, idx)
        if fr is None:
            return float("nan")
        a = ctx.kp(fr, upper, view, Side.LEFT)
        b = ctx.kp(fr, lower, view, Side.RIGHT)
        if not (a and b):
            return float("nan")
        return (a.height - b.height) / norm

    return per_cycle(view, fn)


def line_angle_difference(view: View, line_a: tuple[str, str], line_b: tuple[str, str], at_fraction: float = 0.6):
    """Diferença angular entre duas linhas corporais (ex.: ancas vs ombros)."""

    def fn(ctx: MetricContext, seg: Segment) -> float:
        idx = seg.start + int(round((seg.end - seg.start) * at_fraction))
        fr = ctx.frame(view, idx)
        if fr is None:
            return float("nan")
        a1 = fr.get(f"left_{line_a[0]}")
        a2 = fr.get(f"right_{line_a[1]}")
        b1 = fr.get(f"left_{line_b[0]}")
        b2 = fr.get(f"right_{line_b[1]}")
        if not all((a1, a2, b1, b2)):
            return float("nan")
        return abs(
            angle_to_horizontal(a1, a2) - angle_to_horizontal(b1, b2)
        )

    return per_cycle(view, fn)
