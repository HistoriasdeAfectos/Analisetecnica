"""Segmentação temporal — a diferença estrutural entre desportos.

Três estratégias, todas devolvendo `list[Segment]`, que é o que o cálculo de
métricas consome:

- `CyclicSegmenter`  — corrida, ciclismo, natação
- `PhaseSegmenter`   — tiro com arco, lançamentos
- `InstantSegmenter` — modo fotografia e postura estática
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np

from .types import PoseFrame, PoseSequence, Segment

SignalFn = Callable[[PoseFrame], float]
EventFn = Callable[[PoseSequence], list[int]]


class Segmenter(Protocol):
    def segment(self, seq: PoseSequence) -> list[Segment]: ...


def _extract(seq: PoseSequence, fn: SignalFn) -> np.ndarray:
    out = np.full(len(seq.frames), np.nan)
    for i, f in enumerate(seq.frames):
        try:
            v = fn(f)
        except (KeyError, AttributeError, TypeError):
            v = float("nan")
        out[i] = v if v is not None else float("nan")
    return out


def dominant_period(signal: np.ndarray) -> float:
    """Período dominante do sinal, em frames, por análise espectral.

    Evita ter de afinar à mão a separação mínima entre eventos por desporto e
    por cadência. Sem isto, um segundo máximo local dentro do apoio faz o
    segmentador contar passos onde devia contar passadas — erro de factor 2
    que se propaga a todas as métricas por ciclo.
    """
    finite = ~np.isnan(signal)
    if finite.sum() < 16:
        return 0.0
    x = signal.copy()
    idx = np.arange(len(x))
    x[~finite] = np.interp(idx[~finite], idx[finite], x[finite])
    x = x - x.mean()
    if not np.any(x):
        return 0.0
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    if len(spectrum) < 3:
        return 0.0
    k = int(np.argmax(spectrum[1:])) + 1
    return len(x) / k if k else 0.0


def find_extrema(signal: np.ndarray, kind: str = "min", min_separation: int = 5) -> list[int]:
    """Detecta mínimos ou máximos locais com separação mínima imposta.

    Implementação deliberadamente simples: os eventos detectados aqui são o
    ponto mais frágil do pipeline na corrida, e a interface deve permitir
    revisão manual em vez de confiar cegamente nesta heurística.
    """
    s = -signal if kind == "max" else signal
    n = len(s)
    candidates = []
    for i in range(1, n - 1):
        if np.isnan(s[i - 1]) or np.isnan(s[i]) or np.isnan(s[i + 1]):
            continue
        if s[i] <= s[i - 1] and s[i] < s[i + 1]:
            candidates.append(i)
        elif s[i] < s[i - 1] and s[i] <= s[i + 1]:
            candidates.append(i)

    accepted: list[int] = []
    for i in candidates:
        if accepted and i - accepted[-1] < min_separation:
            if s[i] < s[accepted[-1]]:
                accepted[-1] = i
            continue
        accepted.append(i)
    return accepted


@dataclass
class CyclicSegmenter:
    """Segmenta por repetição de um evento periódico.

    `signal` extrai um escalar por frame; os ciclos são delimitados pelos
    extremos desse sinal. `phase_variable` documenta o eixo de normalização —
    no ciclismo é o ângulo da manivela, não o tempo.
    """

    signal: SignalFn
    cycle_event: str = "cycle_start"
    kind: str = "min"
    min_separation: int = 5
    phase_variable: str = "time"
    min_cycles: int = 2
    auto_separation: bool = True

    def segment(self, seq: PoseSequence) -> list[Segment]:
        if len(seq.frames) < 3:
            return []
        sig = _extract(seq, self.signal)
        separation = self.min_separation
        if self.auto_separation:
            period = dominant_period(sig)
            if period:
                separation = max(separation, int(0.6 * period))
        marks = find_extrema(sig, self.kind, separation)
        segments = []
        for i in range(len(marks) - 1):
            segments.append(
                Segment(
                    start=marks[i],
                    end=marks[i + 1],
                    label="cycle",
                    index=i,
                    events={self.cycle_event: marks[i]},
                )
            )
        return segments


@dataclass
class PhaseSegmenter:
    """Segmenta por sequência de fases discretas delimitadas por eventos.

    `anchor_event` é o evento mais fiável de detectar (no arco e nos
    lançamentos, a largada). As fases restantes localizam-se relativamente a
    ele, através de `offsets` em fracção da janela disponível.
    """

    phases: list[str]
    anchor_event: str
    anchor_detector: EventFn
    pre_frames: int = 60
    post_frames: int = 30
    repetition_label: str = "repetition"

    def segment(self, seq: PoseSequence) -> list[Segment]:
        anchors = self.anchor_detector(seq)
        n = len(seq.frames)
        segments: list[Segment] = []
        for r, a in enumerate(anchors):
            start = max(0, a - self.pre_frames)
            end = min(n - 1, a + self.post_frames)
            if end <= start:
                continue
            # Divisão uniforme das fases anteriores à âncora. É uma
            # aproximação: fases reais têm durações desiguais e a afinação
            # exige detectores próprios por prova.
            pre = self.phases[:-1] or self.phases
            span = a - start
            events = {self.anchor_event: a}
            for k, name in enumerate(pre):
                events[name] = start + int(span * k / max(1, len(pre)))
            segments.append(
                Segment(start=start, end=end, label=self.repetition_label, index=r, events=events)
            )
        return segments


@dataclass
class InstantSegmenter:
    """Modo fotografia e postura estática.

    Exige `tagged_event` na sequência: duas capturas só são comparáveis se
    representarem o mesmo instante do gesto (ARCHITECTURE.md §2.3).
    """

    required_event: str | None = None
    accepted_events: list[str] = field(default_factory=list)

    def segment(self, seq: PoseSequence) -> list[Segment]:
        if not seq.frames:
            return []
        event = seq.tagged_event or self.required_event
        if event is None:
            raise ValueError(
                "Modo instantâneo exige `tagged_event` na captura: sem saber que "
                "instante a imagem representa, a comparação entre sessões não tem "
                "significado técnico."
            )
        if self.accepted_events and event not in self.accepted_events:
            raise ValueError(
                f"Evento '{event}' não pertence a este perfil. Aceites: "
                f"{', '.join(self.accepted_events)}"
            )
        mid = len(seq.frames) // 2
        return [Segment(start=mid, end=mid, label=event, index=0, events={event: mid})]
