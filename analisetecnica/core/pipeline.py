"""Orquestração: captura → filtragem → segmentação → métricas → score → relatório."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import filtering, scoring
from .metrics import MetricContext, MetricSpec
from .profile import ReferenceSet, SportProfile
from .scoring import MetricResult, Progress, Score
from .types import (
    Calibration,
    Confidence,
    MetricValue,
    PoseSequence,
    Segment,
    Side,
    Validity,
    View,
)


@dataclass
class Analysis:
    profile: SportProfile
    athlete: str
    results: list[MetricResult]
    score: Score
    segments: list[Segment]
    filter_reports: dict[View, filtering.FilterReport] = field(default_factory=dict)
    progress: Progress | None = None
    warnings: list[str] = field(default_factory=list)

    def result(self, key: str) -> MetricResult | None:
        return next((r for r in self.results if r.value.key == key or r.spec.id == key), None)


def _compute_metric(
    spec: MetricSpec, ctx: MetricContext, side: Side | None
) -> MetricValue:
    ctx.side = side
    validity = spec.check_validity(ctx)
    value = MetricValue(
        metric_id=spec.id,
        values=[],
        unit=spec.unit,
        side=side,
        validity=validity,
        definition_version=spec.definition_version,
    )
    if not validity.is_usable:
        return value

    try:
        raw = spec.compute(ctx)
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        value.validity = Validity.MISSING_KEYPOINTS
        value.notes.append(f"cálculo falhou: {exc}")
        return value

    value.values = [v for v in (raw or []) if v is not None and not math.isnan(v)]
    if not value.values:
        value.validity = Validity.MISSING_KEYPOINTS
        value.notes.append("sem amostras válidas")
    if spec.caveat:
        value.notes.append(spec.caveat)
    return value


def run(
    profile: SportProfile,
    sequences: dict[View, PoseSequence],
    *,
    athlete: str = "",
    calibration: Calibration | None = None,
    reference: ReferenceSet | None = None,
    baseline: "Analysis | None" = None,
) -> Analysis:
    warnings: list[str] = []

    missing = [v.value for v in profile.required_views() if v not in sequences]
    if missing:
        raise ValueError(
            f"perfil '{profile.id}' exige a(s) vista(s) {', '.join(missing)}"
        )

    # 1. Filtragem. A sequência crua é preservada para as métricas de tremor.
    filtered: dict[View, PoseSequence] = {}
    reports: dict[View, filtering.FilterReport] = {}
    for view, seq in sequences.items():
        filtered[view], reports[view] = filtering.apply(seq, profile.filter_spec)
        if reports[view].smoothing_skipped_reason:
            warnings.append(
                f"{view.value}: suavização não aplicada ({reports[view].smoothing_skipped_reason})"
            )

    # 2. Segmentação, sempre sobre a vista principal.
    primary = profile.primary_view
    segments = profile.segmenter().segment(filtered[primary])
    if len(segments) < profile.min_repetitions:
        warnings.append(
            f"detectadas {len(segments)} repetições; o perfil recomenda pelo menos "
            f"{profile.min_repetitions}. Resultados pouco robustos."
        )

    ctx = MetricContext(
        sequences=filtered,
        raw=sequences,
        lateralities=profile.lateralities,
        segments=segments,
        calibration=calibration,
    )

    # 3. Métricas.
    results: list[MetricResult] = []
    for spec in profile.metrics:
        sides = [Side.LEFT, Side.RIGHT] if spec.bilateral else [None]
        for side in sides:
            value = _compute_metric(spec, ctx, side)
            band = reference.band_for(value.key) if reference else None
            results.append(scoring.evaluate(spec, value, band))

    # 4. Confiança e score.
    fps = next((s.fps for s in sequences.values() if s.fps), None)
    pose_conf = (
        sum(s.mean_confidence for s in sequences.values()) / len(sequences)
        if sequences
        else 0.0
    )
    confidence = Confidence(
        pose_confidence=pose_conf,
        effective_fps=fps,
        has_calibration=calibration is not None,
        repetitions=len(segments),
    )
    score = scoring.aggregate(results, confidence)

    if reference and reference.weak:
        warnings.append(
            "referência fraca (n=1) em: " + ", ".join(sorted(reference.weak))
        )

    progress = (
        scoring.compare_to_baseline(results, baseline.results, baseline.athlete)
        if baseline
        else None
    )

    return Analysis(
        profile=profile,
        athlete=athlete,
        results=results,
        score=score,
        segments=segments,
        filter_reports=reports,
        progress=progress,
        warnings=warnings,
    )
