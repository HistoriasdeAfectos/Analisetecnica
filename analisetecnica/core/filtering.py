"""Camada de filtragem entre pose e cálculo. Obrigatória (ARCHITECTURE.md §2.5).

Excepção documentada: as métricas de tremor e estabilidade calculam-se sobre o
sinal *antes* da suavização. Por isso `apply()` devolve a sequência filtrada mas
nunca destrói a original — quem precisa do sinal cru usa a sequência de entrada.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, filtfilt, savgol_filter

from .types import PoseFrame, PoseSequence, Point


@dataclass
class FilterSpec:
    confidence_threshold: float = 0.5
    gap_interpolation: str = "spline"  # "linear" | "spline" | "none"
    max_gap_frames: int = 4
    smoothing: str = "butterworth"  # "butterworth" | "savitzky_golay" | "none"
    order: int = 4
    cutoff_hz: float = 6.0
    window: int = 9
    polyorder: int = 3


@dataclass
class FilterReport:
    dropped_by_confidence: int = 0
    interpolated: int = 0
    unrecoverable: dict[str, int] = None  # keypoint -> nº de frames sem dado
    smoothing_applied: bool = False
    smoothing_skipped_reason: str = ""

    def __post_init__(self) -> None:
        if self.unrecoverable is None:
            self.unrecoverable = {}


def _series(frames: list[PoseFrame], name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(frames)
    xs = np.full(n, np.nan)
    ys = np.full(n, np.nan)
    cs = np.zeros(n)
    for i, f in enumerate(frames):
        p = f.get(name)
        if p is not None:
            xs[i], ys[i], cs[i] = p.x, p.y, p.confidence
    return xs, ys, cs


def _interpolate(arr: np.ndarray, max_gap: int, method: str) -> tuple[np.ndarray, int]:
    """Preenche lacunas curtas. Lacunas acima de `max_gap` ficam NaN."""
    if method == "none":
        return arr, 0
    valid = ~np.isnan(arr)
    if valid.sum() < 2:
        return arr, 0
    out = arr.copy()
    idx = np.arange(len(arr))
    filled = 0

    start = None
    for i in range(len(arr)):
        if np.isnan(arr[i]):
            if start is None:
                start = i
        else:
            if start is not None:
                gap = i - start
                if gap <= max_gap and start > 0:
                    out[start:i] = np.interp(idx[start:i], idx[valid], arr[valid])
                    filled += gap
                start = None
    return out, filled


def _smooth(arr: np.ndarray, spec: FilterSpec, fps: float) -> tuple[np.ndarray, bool, str]:
    finite = ~np.isnan(arr)
    if finite.sum() < 4:
        return arr, False, "amostras insuficientes"
    if spec.smoothing == "none":
        return arr, False, "desactivada no perfil"

    work = arr.copy()
    # Suavizar só o troço contínuo conhecido; NaN é restaurado no fim.
    idx = np.arange(len(arr))
    work[~finite] = np.interp(idx[~finite], idx[finite], arr[finite])

    if spec.smoothing == "butterworth":
        nyquist = fps / 2.0
        if spec.cutoff_hz >= nyquist:
            return arr, False, f"corte {spec.cutoff_hz} Hz >= Nyquist {nyquist:.1f} Hz"
        padlen = 3 * spec.order
        if len(work) <= padlen:
            return arr, False, "sequência demasiado curta para filtfilt"
        b, a = butter(spec.order, spec.cutoff_hz / nyquist, btype="low")
        work = filtfilt(b, a, work)
    elif spec.smoothing == "savitzky_golay":
        win = min(spec.window, len(work) if len(work) % 2 else len(work) - 1)
        if win <= spec.polyorder:
            return arr, False, "janela demasiado curta"
        work = savgol_filter(work, win, spec.polyorder)

    work[~finite] = np.nan
    return work, True, ""


def apply(seq: PoseSequence, spec: FilterSpec) -> tuple[PoseSequence, FilterReport]:
    """Devolve uma nova sequência filtrada. A original permanece intacta."""
    report = FilterReport()
    if not seq.frames:
        return seq, report

    names = sorted({n for f in seq.frames for n in f.keypoints})
    fps = seq.fps or 0.0
    n = len(seq.frames)
    out: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    for name in names:
        xs, ys, cs = _series(seq.frames, name)

        low = cs < spec.confidence_threshold
        report.dropped_by_confidence += int(low.sum())
        xs[low] = np.nan
        ys[low] = np.nan

        xs, f1 = _interpolate(xs, spec.max_gap_frames, spec.gap_interpolation)
        ys, f2 = _interpolate(ys, spec.max_gap_frames, spec.gap_interpolation)
        report.interpolated += f1

        missing = int(np.isnan(xs).sum())
        if missing:
            report.unrecoverable[name] = missing

        # Fotografia e sequências muito curtas não são suavizáveis; isso é
        # esperado no modo `instant`, não um defeito.
        if n > 1 and fps > 0:
            xs, ok, why = _smooth(xs, spec, fps)
            ys, _, _ = _smooth(ys, spec, fps)
            report.smoothing_applied = report.smoothing_applied or ok
            if not ok and why and not report.smoothing_skipped_reason:
                report.smoothing_skipped_reason = why
        elif not report.smoothing_skipped_reason:
            report.smoothing_skipped_reason = "sem fps ou frame único"

        out[name] = (xs, ys, cs)

    frames = []
    for i in range(n):
        kps: dict[str, Point] = {}
        for name, (xs, ys, cs) in out.items():
            if not np.isnan(xs[i]) and not np.isnan(ys[i]):
                kps[name] = Point(float(xs[i]), float(ys[i]), float(cs[i]))
        frames.append(PoseFrame(index=seq.frames[i].index, keypoints=kps))

    filtered = PoseSequence(
        frames=frames,
        view=seq.view,
        fps=seq.fps,
        source_id=seq.source_id,
        calibration=seq.calibration,
        tagged_event=seq.tagged_event,
        device=dict(seq.device),
    )
    return filtered, report
