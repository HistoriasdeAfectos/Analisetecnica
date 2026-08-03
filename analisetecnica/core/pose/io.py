"""Persistência de keypoints em bruto.

Invariante do projecto: os keypoints são retidos permanentemente. As fórmulas
das métricas vão mudar; sem os keypoints, todo o histórico fica incomparável a
cada afinação. Com eles, recalcula-se tudo (ARCHITECTURE.md §1.4).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..types import Calibration, Point, PoseFrame, PoseSequence, View

FORMAT_VERSION = 1


def to_dict(seq: PoseSequence) -> dict:
    return {
        "format_version": FORMAT_VERSION,
        "view": seq.view.value,
        "fps": seq.fps,
        "source_id": seq.source_id,
        "tagged_event": seq.tagged_event,
        "device": seq.device,
        "calibration": (
            {
                "pixels_per_meter": seq.calibration.pixels_per_meter,
                "reference_object": seq.calibration.reference_object,
            }
            if seq.calibration
            else None
        ),
        "frames": [
            {
                "i": f.index,
                "k": {
                    name: [round(p.x, 6), round(p.y, 6), round(p.confidence, 4)]
                    for name, p in f.keypoints.items()
                },
            }
            for f in seq.frames
        ],
    }


def from_dict(data: dict) -> PoseSequence:
    version = data.get("format_version", 1)
    if version > FORMAT_VERSION:
        raise ValueError(
            f"ficheiro de keypoints em formato {version}, superior ao suportado "
            f"({FORMAT_VERSION})"
        )
    cal = data.get("calibration")
    return PoseSequence(
        frames=[
            PoseFrame(
                index=fr["i"],
                keypoints={
                    name: Point(v[0], v[1], v[2] if len(v) > 2 else 1.0)
                    for name, v in fr["k"].items()
                },
            )
            for fr in data["frames"]
        ],
        view=View(data["view"]),
        fps=data.get("fps"),
        source_id=data.get("source_id", ""),
        tagged_event=data.get("tagged_event"),
        device=data.get("device", {}),
        calibration=(
            Calibration(cal["pixels_per_meter"], cal.get("reference_object", ""))
            if cal
            else None
        ),
    )


def save(seq: PoseSequence, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(to_dict(seq), ensure_ascii=False), encoding="utf-8")
    return p


def load(path: str | Path) -> PoseSequence:
    return from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
