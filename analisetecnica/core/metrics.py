"""Definição de métricas: contexto de cálculo, alvos e especificação.

O texto de recomendação vive na `MetricSpec` (ARCHITECTURE.md §2.7). Centralizá-lo
transformaria o módulo de relatório num `switch` por desporto.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from . import keypoints as kp
from .geometry import distance, midpoint
from .types import (
    Band,
    Calibration,
    Laterality,
    Plane,
    Point,
    PoseFrame,
    PoseSequence,
    Requires,
    Segment,
    Side,
    Validity,
    View,
)


# --------------------------------------------------------------------------- #
# Contexto de cálculo
# --------------------------------------------------------------------------- #


@dataclass
class MetricContext:
    """Tudo o que uma métrica pode consultar. Nada específico de um desporto."""

    sequences: dict[View, PoseSequence]
    raw: dict[View, PoseSequence]
    lateralities: dict[View, Laterality]
    segments: list[Segment]
    side: Side | None = None
    calibration: Calibration | None = None
    default_side: Side = Side.RIGHT

    # -- acesso -------------------------------------------------------------
    def seq(self, view: View, *, raw: bool = False) -> PoseSequence:
        """Sequência de uma vista. `raw=True` devolve o sinal antes da suavização.

        Usado pelas métricas de tremor e estabilidade, onde filtrar removeria
        precisamente o que se pretende medir.
        """
        source = self.raw if raw else self.sequences
        if view not in source:
            raise KeyError(f"vista {view.value} não disponível")
        return source[view]

    def frame(self, view: View, index: int, *, raw: bool = False) -> PoseFrame | None:
        s = self.seq(view, raw=raw)
        if 0 <= index < len(s.frames):
            return s.frames[index]
        return None

    def kp(self, frame: PoseFrame, base: str, view: View, side: Side | None = None) -> Point | None:
        """Keypoint resolvido, com a lateralidade da vista já aplicada.

        Numa métrica não bilateral (`side is None`) um nome como "hip" não
        existe no esquema canónico, que só tem `left_hip`/`right_hip`. Nesse
        caso usa-se `default_side` — na vista lateral é o membro próximo da
        câmara, o único que a métrica pode observar sem oclusão.
        """
        laterality = self.lateralities.get(view, Laterality.DIRECT)
        effective = side if side is not None else self.side
        name = kp.resolve(base, effective, laterality)
        point = frame.get(name)
        if point is None and effective is None:
            point = frame.get(kp.resolve(base, self.default_side, laterality))
        return point

    def kps(self, frame: PoseFrame, view: View, *bases: str) -> tuple[Point, ...] | None:
        out = []
        for b in bases:
            p = self.kp(frame, b, view)
            if p is None:
                return None
            out.append(p)
        return tuple(out)

    def has_view(self, view: View) -> bool:
        return view in self.sequences and len(self.sequences[view].frames) > 0

    @property
    def fps(self) -> float | None:
        for s in self.sequences.values():
            if s.fps:
                return s.fps
        return None

    # -- normalizadores adimensionais ---------------------------------------
    def _median_over_frames(self, view: View, fn: Callable[[PoseFrame], float | None]) -> float:
        vals = []
        for f in self.seq(view).frames:
            try:
                v = fn(f)
            except (KeyError, TypeError, AttributeError):
                v = None
            if v is not None and not math.isnan(v) and v > 0:
                vals.append(v)
        if not vals:
            return float("nan")
        vals.sort()
        return vals[len(vals) // 2]

    def leg_length(self, view: View) -> float:
        """Anca→joelho→tornozelo, mediana ao longo da sequência."""

        def f(fr: PoseFrame) -> float | None:
            pts = self.kps(fr, view, "hip", "knee", "ankle")
            if pts is None:
                return None
            return distance(pts[0], pts[1]) + distance(pts[1], pts[2])

        return self._median_over_frames(view, f)

    def femur_length(self, view: View) -> float:
        def f(fr: PoseFrame) -> float | None:
            pts = self.kps(fr, view, "hip", "knee")
            return distance(*pts) if pts else None

        return self._median_over_frames(view, f)

    def shoulder_width(self, view: View) -> float:
        def f(fr: PoseFrame) -> float | None:
            a, b = fr.get("left_shoulder"), fr.get("right_shoulder")
            return distance(a, b) if a and b else None

        return self._median_over_frames(view, f)

    def hip_width(self, view: View) -> float:
        def f(fr: PoseFrame) -> float | None:
            a, b = fr.get("left_hip"), fr.get("right_hip")
            return distance(a, b) if a and b else None

        return self._median_over_frames(view, f)

    def stature(self, view: View) -> float:
        """Aproximação: nariz→ponto médio das ancas + comprimento da perna."""

        def f(fr: PoseFrame) -> float | None:
            nose = fr.get("nose")
            lh, rh = fr.get("left_hip"), fr.get("right_hip")
            if not (nose and lh and rh):
                return None
            return distance(nose, midpoint(lh, rh))

        trunk = self._median_over_frames(view, f)
        leg = self.leg_length(view)
        if math.isnan(trunk) or math.isnan(leg):
            return float("nan")
        return trunk + leg

    def center_of_mass(self, frame: PoseFrame) -> Point | None:
        """Aproximação por média ponderada de tronco e ancas."""
        names = ["left_shoulder", "right_shoulder", "left_hip", "right_hip"]
        weights = [0.2, 0.2, 0.3, 0.3]
        acc_x = acc_y = acc_w = 0.0
        for n, w in zip(names, weights):
            p = frame.get(n)
            if p is None:
                continue
            acc_x += p.x * w
            acc_y += p.y * w
            acc_w += w
        if acc_w == 0:
            return None
        return Point(acc_x / acc_w, acc_y / acc_w)


# --------------------------------------------------------------------------- #
# Alvos
# --------------------------------------------------------------------------- #


@dataclass
class TargetResult:
    score: float          # 0–100
    deviation: float      # fracção do intervalo aceitável (base da classificação)
    direction: str        # "ok" | "above" | "below" | "inconsistent"


class Target:
    """Como pontuar uma métrica. Ver ARCHITECTURE.md §4.2."""

    def evaluate(self, value: float, band: Band | None = None) -> TargetResult:
        raise NotImplementedError


@dataclass
class BandTarget(Target):
    """Faixa óptima. 100 dentro, decaindo com a distância à fronteira."""

    low: float
    high: float
    tolerance: float | None = None

    def evaluate(self, value: float, band: Band | None = None) -> TargetResult:
        width = self.high - self.low
        tol = self.tolerance if self.tolerance is not None else max(width, 1e-9)
        if value < self.low:
            excess, direction = self.low - value, "below"
        elif value > self.high:
            excess, direction = value - self.high, "above"
        else:
            return TargetResult(100.0, 0.0, "ok")
        deviation = excess / tol
        return TargetResult(max(0.0, 100.0 * (1.0 - deviation)), deviation, direction)


@dataclass
class MinimizeTarget(Target):
    good: float
    bad: float

    def evaluate(self, value: float, band: Band | None = None) -> TargetResult:
        if value <= self.good:
            return TargetResult(100.0, 0.0, "ok")
        span = max(self.bad - self.good, 1e-9)
        deviation = (value - self.good) / span
        return TargetResult(max(0.0, 100.0 * (1.0 - deviation)), deviation, "above")


@dataclass
class MaximizeTarget(Target):
    good: float
    bad: float

    def evaluate(self, value: float, band: Band | None = None) -> TargetResult:
        if value >= self.good:
            return TargetResult(100.0, 0.0, "ok")
        span = max(self.good - self.bad, 1e-9)
        deviation = (self.good - value) / span
        return TargetResult(max(0.0, 100.0 * (1.0 - deviation)), deviation, "below")


@dataclass
class MatchReferenceTarget(Target):
    """Aproximar-se da banda de referência, medido em desvios-padrão.

    Não usa diferença percentual: sobre valores que podem aproximar-se de zero
    a divisão explode (ARCHITECTURE.md §4.2).
    """

    sd_for_zero: float = 4.0

    def evaluate(self, value: float, band: Band | None = None) -> TargetResult:
        if band is None:
            return TargetResult(float("nan"), float("nan"), "ok")
        if band.sd <= 0:
            return TargetResult(100.0 if value == band.mean else 0.0, 0.0, "ok")
        z = band.z(value)
        deviation = abs(z) / self.sd_for_zero
        direction = "ok" if abs(z) <= 1 else ("above" if z > 0 else "below")
        return TargetResult(max(0.0, 100.0 * (1.0 - deviation)), deviation, direction)


@dataclass
class ConsistencyTarget(Target):
    """Pontua a variabilidade entre repetições, não o valor.

    É o alvo dominante no tiro com arco: a precisão exigida é de escala
    inferior ao ruído da pose 2D, e a variância entre N repetições é mais
    robusta do que qualquer medição isolada.
    """

    good_cv: float = 0.02
    bad_cv: float = 0.15
    basis: str = "cv"  # "cv" | "sd"

    def evaluate(self, value: float, band: Band | None = None) -> TargetResult:
        if value <= self.good_cv:
            return TargetResult(100.0, 0.0, "ok")
        span = max(self.bad_cv - self.good_cv, 1e-9)
        deviation = (value - self.good_cv) / span
        return TargetResult(max(0.0, 100.0 * (1.0 - deviation)), deviation, "inconsistent")

    def dispersion(self, mean: float, sd: float, cv: float) -> float:
        """Grandeza a pontuar.

        `basis="sd"` existe para quantidades que podem aproximar-se de zero —
        uma diferença de altura entre ombros, por exemplo. Aí o coeficiente de
        variação explode por divisão, e o desvio-padrão absoluto (já
        adimensional, por normalização corporal) é a leitura correcta.
        """
        return sd if self.basis == "sd" else cv


# --------------------------------------------------------------------------- #
# Especificação
# --------------------------------------------------------------------------- #


@dataclass
class Recommendation:
    when: str   # "above" | "below" | "out" | "inconsistent"
    text: str


ComputeFn = Callable[[MetricContext], list[float]]


@dataclass
class MetricSpec:
    id: str
    name: str
    views: list[View]
    bases: list[str]
    compute: ComputeFn
    target: Target
    unit: str
    requires: Requires = Requires.NONE
    min_fps: float | None = None
    bilateral: bool = False
    weight: float = 1.0
    group: str = "geral"
    plane: Plane | None = None
    uses_raw_signal: bool = False
    definition_version: str = "0.1.0"
    recommendations: list[Recommendation] = field(default_factory=list)
    caveat: str = ""

    def recommendation_for(self, direction: str) -> str:
        for r in self.recommendations:
            if r.when == direction or (r.when == "out" and direction in ("above", "below")):
                return r.text
        return ""

    def check_validity(self, ctx: MetricContext) -> Validity:
        for v in self.views:
            if not ctx.has_view(v):
                return Validity.MISSING_KEYPOINTS
        if self.requires is Requires.CALIBRATION and ctx.calibration is None:
            return Validity.MISSING_CALIBRATION
        if self.min_fps:
            fps = ctx.fps
            if fps is None or fps < self.min_fps:
                return Validity.INSUFFICIENT_FPS
        conf = min(ctx.sequences[v].mean_confidence for v in self.views)
        if conf < 0.5:
            return Validity.LOW_CONFIDENCE
        return Validity.OK
