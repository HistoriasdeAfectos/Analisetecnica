"""Tipos centrais partilhados por todo o pipeline.

Convenção de coordenadas: coordenadas de imagem normalizadas, com origem no
canto superior esquerdo e **y a crescer para baixo**. Usar `altura()` sempre que
se pretenda "mais alto = maior", em vez de comparar `y` directamente — é a fonte
de erro de sinal mais comum neste código.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class View(str, Enum):
    LATERAL = "lateral"
    FRONTAL = "frontal"
    POSTERIOR = "posterior"
    SUPERIOR = "superior"
    INFERIOR = "inferior"


class Plane(str, Enum):
    SAGITTAL = "sagittal"
    FRONTAL = "frontal"
    TRANSVERSE = "transverse"


class Laterality(str, Enum):
    DIRECT = "direct"
    MIRRORED = "mirrored"


class Requires(str, Enum):
    """O que uma métrica exige para ser válida (ver ARCHITECTURE.md §1.2)."""

    NONE = "none"
    FPS = "fps"
    CALIBRATION = "calibration"


class Validity(str, Enum):
    OK = "ok"
    LOW_CONFIDENCE = "low_confidence"
    INSUFFICIENT_FPS = "insufficient_fps"
    MISSING_CALIBRATION = "missing_calibration"
    MISSING_KEYPOINTS = "missing_keypoints"
    OUT_OF_PLANE = "out_of_plane"
    INSUFFICIENT_REPETITIONS = "insufficient_repetitions"

    @property
    def is_usable(self) -> bool:
        return self in (Validity.OK, Validity.LOW_CONFIDENCE, Validity.OUT_OF_PLANE)


class Side(str, Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    confidence: float = 1.0
    z: float | None = None

    @property
    def height(self) -> float:
        """Altura crescente para cima. `y` de imagem cresce para baixo."""
        return -self.y


@dataclass
class PoseFrame:
    index: int
    keypoints: dict[str, Point]

    def get(self, name: str) -> Point | None:
        return self.keypoints.get(name)

    def has(self, names: Iterable[str]) -> bool:
        return all(n in self.keypoints for n in names)

    @property
    def mean_confidence(self) -> float:
        if not self.keypoints:
            return 0.0
        return sum(p.confidence for p in self.keypoints.values()) / len(self.keypoints)


@dataclass
class Calibration:
    """Escala métrica. `pixels_per_meter` em unidades normalizadas de imagem."""

    pixels_per_meter: float
    reference_object: str = ""

    def to_meters(self, normalized_distance: float) -> float:
        return normalized_distance / self.pixels_per_meter


@dataclass
class PoseSequence:
    """Sequência de frames de uma única vista. Uma fotografia tem comprimento 1."""

    frames: list[PoseFrame]
    view: View
    fps: float | None = None
    source_id: str = ""
    calibration: Calibration | None = None
    tagged_event: str | None = None
    device: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.frames)

    @property
    def is_photo(self) -> bool:
        return len(self.frames) <= 1

    @property
    def mean_confidence(self) -> float:
        if not self.frames:
            return 0.0
        return sum(f.mean_confidence for f in self.frames) / len(self.frames)

    def duration_s(self) -> float | None:
        if not self.fps or self.fps <= 0:
            return None
        return len(self.frames) / self.fps


@dataclass
class Segment:
    """Um ciclo, uma fase ou um instante. Saída unificada da segmentação."""

    start: int
    end: int
    label: str = "cycle"
    index: int = 0
    events: dict[str, int] = field(default_factory=dict)

    def __len__(self) -> int:
        return max(0, self.end - self.start + 1)

    def phase_at(self, frame_index: int) -> float:
        """Posição no segmento em percentagem (0–100)."""
        span = self.end - self.start
        if span <= 0:
            return 0.0
        return 100.0 * (frame_index - self.start) / span


@dataclass
class Band:
    """Referência: média ± desvio-padrão. Nunca um valor único."""

    mean: float
    sd: float
    samples: int = 0

    @property
    def is_weak(self) -> bool:
        return self.samples <= 1

    def z(self, value: float) -> float:
        if self.sd <= 0:
            return 0.0
        return (value - self.mean) / self.sd


@dataclass
class MetricValue:
    metric_id: str
    values: list[float]
    unit: str
    side: Side | None = None
    validity: Validity = Validity.OK
    notes: list[str] = field(default_factory=list)
    definition_version: str = "0.1.0"

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> float:
        return sum(self.values) / len(self.values) if self.values else float("nan")

    @property
    def sd(self) -> float:
        if len(self.values) < 2:
            return 0.0
        m = self.mean
        return (sum((v - m) ** 2 for v in self.values) / (len(self.values) - 1)) ** 0.5

    @property
    def cv(self) -> float:
        """Coeficiente de variação. Base das métricas de repetibilidade."""
        m = self.mean
        return abs(self.sd / m) if m else float("nan")

    @property
    def key(self) -> str:
        return f"{self.metric_id}:{self.side.value}" if self.side else self.metric_id


@dataclass
class Confidence:
    """Qualidade dos dados que sustentam um score (ARCHITECTURE.md §4.4)."""

    pose_confidence: float
    effective_fps: float | None
    has_calibration: bool
    repetitions: int
    sync_error_ms: float | None = None

    @property
    def level(self) -> str:
        score = 0
        score += 2 if self.pose_confidence >= 0.7 else 1 if self.pose_confidence >= 0.5 else 0
        score += 2 if (self.effective_fps or 0) >= 120 else 1 if (self.effective_fps or 0) >= 60 else 0
        score += 1 if self.repetitions >= 5 else 0
        score += 1 if self.has_calibration else 0
        return {6: "alta", 5: "alta", 4: "média", 3: "média"}.get(score, "baixa")
