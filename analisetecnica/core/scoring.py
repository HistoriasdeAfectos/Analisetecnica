"""Comparação com referência e pontuação.

Regra estruturante: o score técnico e o score de evolução **nunca se fundem**
(ARCHITECTURE.md §4.1). Um atleta pode melhorar muito e continuar nos 60; um
número único esconde as duas informações.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .metrics import ConsistencyTarget, MetricSpec, TargetResult
from .types import Band, Confidence, MetricValue, Validity

GREEN, YELLOW = 0.05, 0.15


def classify(deviation: float) -> str:
    """Verde/amarelo/vermelho sobre a fracção do intervalo aceitável.

    Deliberadamente **não** é uma percentagem do valor de referência: sobre
    métricas que podem aproximar-se de zero (queda da anca, desvio lateral) essa
    divisão explode.
    """
    if deviation != deviation:  # NaN
        return "indeterminado"
    if deviation < GREEN:
        return "verde"
    if deviation < YELLOW:
        return "amarelo"
    return "vermelho"


@dataclass
class MetricResult:
    spec: MetricSpec
    value: MetricValue
    band: Band | None
    target: TargetResult
    classification: str

    @property
    def score(self) -> float:
        return self.target.score

    @property
    def usable(self) -> bool:
        return self.value.validity.is_usable and self.score == self.score

    @property
    def recommendation(self) -> str:
        if self.classification in ("verde", "indeterminado"):
            return ""
        return self.spec.recommendation_for(self.target.direction)


def evaluate(spec: MetricSpec, value: MetricValue, band: Band | None) -> MetricResult:
    """Avalia uma métrica já calculada contra o seu alvo e a sua banda."""
    if not value.values or value.mean != value.mean:
        return MetricResult(spec, value, band, TargetResult(float("nan"), float("nan"), "ok"), "indeterminado")

    # As métricas de repetibilidade pontuam a variabilidade, não a média.
    if isinstance(spec.target, ConsistencyTarget):
        if value.n < 2:
            value.validity = Validity.INSUFFICIENT_REPETITIONS
            value.notes.append("repetibilidade exige pelo menos 2 repetições")
            return MetricResult(spec, value, band, TargetResult(float("nan"), float("nan"), "ok"), "indeterminado")
        target = spec.target.evaluate(
            spec.target.dispersion(value.mean, value.sd, value.cv), band
        )
    else:
        target = spec.target.evaluate(value.mean, band)

    return MetricResult(spec, value, band, target, classify(target.deviation))


@dataclass
class Score:
    """Nunca apresentar isolado do indicador de confiança."""

    technical: float
    by_group: dict[str, float]
    confidence: Confidence
    covered_weight: float
    total_weight: float
    excluded: list[str] = field(default_factory=list)

    @property
    def is_partial(self) -> bool:
        return self.covered_weight < 0.999 * self.total_weight

    @property
    def banded(self) -> str:
        """Bandas de 5 pontos. `87,3` sugere exactidão que a pose 2D não tem."""
        if self.technical != self.technical:
            return "indeterminado"
        low = int(self.technical // 5) * 5
        return f"{low}–{min(100, low + 5)}"


def aggregate(results: list[MetricResult], confidence: Confidence) -> Score:
    total = sum(r.spec.weight for r in results)
    usable = [r for r in results if r.usable]
    covered = sum(r.spec.weight for r in usable)

    technical = (
        sum(r.score * r.spec.weight for r in usable) / covered if covered > 0 else float("nan")
    )

    groups: dict[str, list[MetricResult]] = {}
    for r in usable:
        groups.setdefault(r.spec.group, []).append(r)
    by_group = {
        g: sum(r.score * r.spec.weight for r in rs) / sum(r.spec.weight for r in rs)
        for g, rs in groups.items()
    }

    excluded = [
        f"{r.spec.id} ({r.value.validity.value})" for r in results if not r.usable
    ]
    return Score(technical, by_group, confidence, covered, total, excluded)


@dataclass
class ProgressEntry:
    metric_id: str
    baseline: float
    current: float

    @property
    def delta(self) -> float:
        return self.current - self.baseline


@dataclass
class Progress:
    """Evolução face à própria baseline do atleta. Independente do score técnico."""

    entries: list[ProgressEntry]
    baseline_label: str = ""

    @property
    def mean_delta(self) -> float:
        if not self.entries:
            return float("nan")
        return sum(e.delta for e in self.entries) / len(self.entries)

    @property
    def improved(self) -> list[ProgressEntry]:
        return sorted([e for e in self.entries if e.delta > 1], key=lambda e: -e.delta)

    @property
    def regressed(self) -> list[ProgressEntry]:
        return sorted([e for e in self.entries if e.delta < -1], key=lambda e: e.delta)


def compare_to_baseline(
    current: list[MetricResult], baseline: list[MetricResult], label: str = ""
) -> Progress:
    prev = {r.value.key: r for r in baseline if r.usable}
    entries = []
    for r in current:
        if not r.usable:
            continue
        b = prev.get(r.value.key)
        if b is None:
            continue
        entries.append(ProgressEntry(r.value.key, b.score, r.score))
    return Progress(entries, label)
