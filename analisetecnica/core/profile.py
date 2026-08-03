"""Perfil de desporto e registo global.

Acrescentar um desporto é escrever um perfil, nunca alterar o pipeline
(ARCHITECTURE.md §1.1). Nada neste módulo — nem em qualquer outro de `core/` —
importa de `sports/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .filtering import FilterSpec
from .metrics import MetricSpec
from .segmentation import Segmenter
from .types import Band, Laterality, Plane, View


@dataclass
class ViewSpec:
    kind: View
    required: bool = False
    laterality: Laterality = Laterality.DIRECT
    plane: Plane = Plane.SAGITTAL
    purpose: str = ""


@dataclass
class ReferenceSet:
    """Sempre banda (média ± desvio). `samples <= 1` é referência fraca."""

    id: str
    kind: str  # "elite_band" | "own_baseline" | "coach_target"
    event: str = ""
    bands: dict[str, Band] = field(default_factory=dict)

    def band_for(self, key: str) -> Band | None:
        if key in self.bands:
            return self.bands[key]
        return self.bands.get(key.split(":")[0])

    @property
    def weak(self) -> list[str]:
        return [k for k, b in self.bands.items() if b.is_weak]


@dataclass
class SportProfile:
    id: str
    name: str
    views: list[ViewSpec]
    segmenter: Callable[[], Segmenter]
    metrics: list[MetricSpec]
    filter_spec: FilterSpec = field(default_factory=FilterSpec)
    group_weights: dict[str, float] = field(default_factory=dict)
    references: list[ReferenceSet] = field(default_factory=list)
    maturity: str = "experimental"
    min_repetitions: int = 1
    pose_backend: str = "mediapipe"
    risks: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._rescale_weights()

    def _rescale_weights(self) -> None:
        """Reparte o peso de cada grupo pelas suas métricas.

        Assim o perfil declara os pesos ao nível a que o treinador raciocina
        (grupos), e cada métrica mantém o seu peso relativo dentro do grupo.
        """
        if not self.group_weights:
            return
        by_group: dict[str, list[MetricSpec]] = {}
        for m in self.metrics:
            by_group.setdefault(m.group, []).append(m)
        for group, specs in by_group.items():
            gw = self.group_weights.get(group)
            if gw is None:
                continue
            inner = sum(m.weight for m in specs) or 1.0
            for m in specs:
                m.weight = gw * m.weight / inner

    @property
    def primary_view(self) -> View:
        for v in self.views:
            if v.required:
                return v.kind
        return self.views[0].kind

    @property
    def lateralities(self) -> dict[View, Laterality]:
        return {v.kind: v.laterality for v in self.views}

    def view_spec(self, view: View) -> ViewSpec | None:
        return next((v for v in self.views if v.kind is view), None)

    def required_views(self) -> list[View]:
        return [v.kind for v in self.views if v.required]

    def metric(self, metric_id: str) -> MetricSpec | None:
        return next((m for m in self.metrics if m.id == metric_id), None)

    def reference(self, kind: str = "elite_band", event: str = "") -> ReferenceSet | None:
        for r in self.references:
            if r.kind == kind and (not event or r.event == event):
                return r
        return next((r for r in self.references if r.kind == kind), None)


_REGISTRY: dict[str, SportProfile] = {}


def register(profile: SportProfile) -> SportProfile:
    _REGISTRY[profile.id] = profile
    return profile


def get(profile_id: str) -> SportProfile:
    if profile_id not in _REGISTRY:
        raise KeyError(
            f"perfil '{profile_id}' desconhecido. Disponíveis: {', '.join(sorted(_REGISTRY))}"
        )
    return _REGISTRY[profile_id]


def available() -> list[SportProfile]:
    return sorted(_REGISTRY.values(), key=lambda p: p.id)
