"""Gerador sintético de pose.

Existe por duas razões práticas:

1. permitir executar e testar o pipeline completo sem vídeo nem modelo de pose;
2. dar aos testes um sinal com verdade conhecida — se a elevação do joelho for
   gerada maior, a métrica tem de subir.

**Não substitui validação com vídeo real.** Os dados aqui são cinematicamente
plausíveis, não medidos: servem para verificar o pipeline, nunca para validar
bandas de referência.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..types import Point, PoseFrame, PoseSequence, View


def _interp_cycle(u: np.ndarray, knots: list[tuple[float, float]]) -> np.ndarray:
    """Interpolação periódica sobre nós (fase, valor)."""
    xs = [k[0] for k in knots] + [knots[0][0] + 1.0]
    ys = [k[1] for k in knots] + [knots[0][1]]
    return np.interp(u % 1.0, xs, ys)


def _noise(rng: np.random.Generator, n: int, sigma: float) -> np.ndarray:
    return rng.normal(0.0, sigma, n)


@dataclass
class SyntheticBackend:
    """`source` é o nome do gerador: "corrida", "ciclismo" ou "arco"."""

    id: str = "synthetic"
    seed: int = 7

    def detect(self, source: str, view: View, **kwargs) -> PoseSequence:
        gen = {
            "corrida": running,
            "ciclismo": cycling,
            "arco": archery,
        }.get(source)
        if gen is None:
            raise KeyError(
                f"gerador sintético '{source}' desconhecido (corrida, ciclismo, arco)"
            )
        return gen(view=view, seed=self.seed, **kwargs)


# --------------------------------------------------------------------------- #
# Corrida
# --------------------------------------------------------------------------- #

FEMUR, TIBIA = 0.150, 0.170
GROUND = 0.760
HIP_BASE = 0.450


def _running_leg(u: np.ndarray, quality: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Ângulos da coxa, flexão do joelho e inclinação do pé ao longo do ciclo.

    `quality` em [0,1] governa a elevação do joelho e o tipo de apoio — é o que
    permite gerar uma sessão "antes" e uma "depois" com evolução real.
    """
    peak_lift = 55.0 + 30.0 * quality          # ângulo máximo da coxa à frente
    strike_pitch = 20.0 - 15.0 * quality       # 20° = calcanhar, 5° = médio/antepé

    thigh = _interp_cycle(u, [
        (0.00, 20.0), (0.15, 0.0), (0.30, -25.0),
        (0.50, -5.0), (0.70, peak_lift), (0.90, 32.0),
    ])
    knee_flex = _interp_cycle(u, [
        (0.00, 15.0), (0.15, 20.0), (0.30, 8.0),
        (0.50, 110.0), (0.70, 88.0), (0.90, 28.0),
    ])
    foot_pitch = _interp_cycle(u, [
        (0.00, strike_pitch), (0.15, 2.0), (0.30, -32.0),
        (0.50, -5.0), (0.70, 12.0), (0.90, strike_pitch),
    ])
    return thigh, knee_flex, foot_pitch


def running(
    view: View = View.LATERAL,
    *,
    n_cycles: int = 6,
    fps: float = 240.0,
    cycle_s: float = 0.72,
    quality: float = 0.8,
    seed: int = 7,
    confidence: float = 0.88,
) -> PoseSequence:
    rng = np.random.default_rng(seed)
    per_cycle = int(round(cycle_s * fps))
    n = per_cycle * n_cycles
    t = np.arange(n)
    u = t / per_cycle

    hip_y = HIP_BASE + 0.012 * np.cos(2 * math.pi * (u - 0.15)) + _noise(rng, n, 0.0012)
    hip_x = np.full(n, 0.450) + _noise(rng, n, 0.0012)

    frames: list[PoseFrame] = []
    sigma = 0.0016

    if view is View.LATERAL:
        thigh_r, flex_r, pitch_r = _running_leg(u, quality)
        thigh_l, flex_l, pitch_l = _running_leg(u + 0.5, quality)
        trunk_lean = 8.0 + 6.0 * (1.0 - quality)

        for i in range(n):
            kps: dict[str, Point] = {}
            hip = Point(float(hip_x[i]), float(hip_y[i]))
            kps["right_hip"] = Point(hip.x, hip.y)
            kps["left_hip"] = Point(hip.x - 0.006, hip.y + 0.002)

            for side, (th, fl, pi) in (
                ("right", (thigh_r[i], flex_r[i], pitch_r[i])),
                ("left", (thigh_l[i], flex_l[i], pitch_l[i])),
            ):
                a_t = math.radians(th)
                a_s = math.radians(th - fl)
                knee = Point(hip.x + FEMUR * math.sin(a_t), hip.y + FEMUR * math.cos(a_t))
                ankle = Point(knee.x + TIBIA * math.sin(a_s), knee.y + TIBIA * math.cos(a_s))
                phi = math.radians(pi)
                toe = Point(ankle.x + 0.075 * math.cos(phi), ankle.y - 0.075 * math.sin(phi))
                heel = Point(ankle.x - 0.028 * math.cos(phi), ankle.y + 0.028 * math.sin(phi))
                # O pé não atravessa o solo.
                toe = Point(toe.x, min(toe.y, GROUND))
                heel = Point(heel.x, min(heel.y, GROUND))

                kps[f"{side}_knee"] = knee
                kps[f"{side}_ankle"] = ankle
                kps[f"{side}_foot_index"] = toe
                kps[f"{side}_heel"] = heel

            lean = math.radians(trunk_lean)
            trunk_len = 0.230
            sh = Point(hip.x + trunk_len * math.sin(lean), hip.y - trunk_len * math.cos(lean))
            kps["right_shoulder"] = sh
            kps["left_shoulder"] = Point(sh.x - 0.010, sh.y + 0.003)
            kps["nose"] = Point(sh.x + 0.042, sh.y - 0.072)
            kps["right_ear"] = Point(sh.x + 0.014, sh.y - 0.080)
            kps["left_ear"] = Point(sh.x + 0.008, sh.y - 0.080)

            # Braços em oposição de fase às pernas.
            arm_r = math.radians(-38.0 * math.cos(2 * math.pi * u[i]))
            arm_l = math.radians(-38.0 * math.cos(2 * math.pi * u[i] + math.pi))
            for side, a in (("right", arm_r), ("left", arm_l)):
                shoulder = kps[f"{side}_shoulder"]
                elbow = Point(shoulder.x + 0.105 * math.sin(a), shoulder.y + 0.105 * math.cos(a))
                fore = a + math.radians(78.0)
                wrist = Point(elbow.x + 0.100 * math.sin(fore), elbow.y + 0.100 * math.cos(fore))
                kps[f"{side}_elbow"] = elbow
                kps[f"{side}_wrist"] = wrist

            frames.append(_jitter(kps, rng, sigma, confidence, i))

    elif view is View.FRONTAL:
        # Queda da anca modulada pelo apoio, cruzamento de braços e joelhos.
        drop_deg = 2.0 + 8.0 * (1.0 - quality)
        hip_w = 0.070
        for i in range(n):
            phase = u[i] % 1.0
            support_r = 1.0 if phase < 0.30 else 0.0
            support_l = 1.0 if 0.5 <= phase < 0.80 else 0.0
            drop = math.tan(math.radians(drop_deg)) * hip_w
            cx = 0.5
            y0 = float(hip_y[i])
            kps = {
                "right_hip": Point(cx + hip_w / 2, y0 + drop * support_l),
                "left_hip": Point(cx - hip_w / 2, y0 + drop * support_r),
                "right_shoulder": Point(cx + 0.056, y0 - 0.225),
                "left_shoulder": Point(cx - 0.056, y0 - 0.225),
                "nose": Point(cx, y0 - 0.300),
                "right_ear": Point(cx + 0.020, y0 - 0.292),
                "left_ear": Point(cx - 0.020, y0 - 0.292),
            }
            for side, sup, ph in (("right", support_r, phase), ("left", support_l, phase + 0.5)):
                sgn = 1 if side == "right" else -1
                swing = 0.5 * (1 - math.cos(2 * math.pi * (ph % 1.0)))
                knee_x = cx + sgn * (hip_w / 2) - sgn * 0.016 * (1 - quality) * swing
                knee_y = y0 + 0.150 - 0.055 * (1 - sup) * swing
                ankle_x = cx + sgn * (hip_w / 2) * 0.55
                ankle_y = y0 + 0.300 - 0.075 * (1 - sup) * swing
                kps[f"{side}_knee"] = Point(knee_x, knee_y)
                kps[f"{side}_ankle"] = Point(ankle_x, ankle_y)
                kps[f"{side}_heel"] = Point(ankle_x - 0.004, ankle_y + 0.020)
                kps[f"{side}_foot_index"] = Point(ankle_x + 0.004, ankle_y + 0.032)
                cross = 0.030 * (1 - quality)
                kps[f"{side}_shoulder"] = kps[f"{side}_shoulder"]
                kps[f"{side}_elbow"] = Point(cx + sgn * 0.062, y0 - 0.115)
                kps[f"{side}_wrist"] = Point(
                    cx + sgn * 0.040 - sgn * cross * swing, y0 - 0.045
                )
            frames.append(_jitter(kps, rng, sigma, confidence, i))
    else:
        raise ValueError(f"gerador de corrida não cobre a vista {view.value}")

    return PoseSequence(
        frames=frames,
        view=view,
        fps=fps,
        source_id=f"synthetic:corrida:{view.value}:q{quality:.2f}",
        device={"backend": "synthetic", "quality": f"{quality:.2f}"},
    )


# --------------------------------------------------------------------------- #
# Ciclismo
# --------------------------------------------------------------------------- #


def cycling(
    view: View = View.LATERAL,
    *,
    n_cycles: int = 8,
    fps: float = 60.0,
    cycle_s: float = 0.70,
    quality: float = 0.8,
    seed: int = 11,
    confidence: float = 0.92,
) -> PoseSequence:
    rng = np.random.default_rng(seed)
    per_cycle = int(round(cycle_s * fps))
    n = per_cycle * n_cycles
    t = np.arange(n)
    u = t / per_cycle
    theta = 2 * math.pi * u  # 0 = ponto morto superior

    bb = Point(0.500, 0.660)
    crank_r = 0.050
    # A altura da anca (proxy da altura de selim) governa a extensão do joelho.
    hip_y = 0.4235 + (1.0 - quality) * 0.024
    frames: list[PoseFrame] = []
    sigma = 0.0011

    if view is View.LATERAL:
        for i in range(n):
            px = bb.x + crank_r * math.sin(theta[i])
            py = bb.y - crank_r * math.cos(theta[i])
            rock = 0.006 * (1 - quality) * math.sin(theta[i])
            hip = Point(0.420, hip_y + rock)
            ankle = Point(px - 0.006, py - 0.020)
            knee = _knee_forward(hip, ankle, 0.135, 0.155)

            shoulder = Point(0.552, hip.y - 0.086)
            elbow = Point(0.610, shoulder.y + 0.050)
            wrist = Point(0.662, shoulder.y + 0.078)

            kps = {
                "right_hip": hip,
                "left_hip": Point(hip.x - 0.008, hip.y + 0.003),
                "right_knee": knee,
                "left_knee": Point(knee.x - 0.008, knee.y + 0.003),
                "right_ankle": ankle,
                "left_ankle": Point(ankle.x - 0.008, ankle.y + 0.003),
                "right_heel": Point(ankle.x - 0.026, ankle.y + 0.012),
                "left_heel": Point(ankle.x - 0.034, ankle.y + 0.015),
                "right_foot_index": Point(ankle.x + 0.044, ankle.y + 0.014),
                "left_foot_index": Point(ankle.x + 0.036, ankle.y + 0.017),
                "right_shoulder": shoulder,
                "left_shoulder": Point(shoulder.x - 0.010, shoulder.y + 0.004),
                "right_elbow": elbow,
                "left_elbow": Point(elbow.x - 0.010, elbow.y + 0.004),
                "right_wrist": wrist,
                "left_wrist": Point(wrist.x - 0.010, wrist.y + 0.004),
                "nose": Point(shoulder.x + 0.060, shoulder.y - 0.030),
                "right_ear": Point(shoulder.x + 0.030, shoulder.y - 0.046),
                "left_ear": Point(shoulder.x + 0.024, shoulder.y - 0.046),
            }
            frames.append(_jitter(kps, rng, sigma, confidence, i))

    elif view in (View.FRONTAL, View.POSTERIOR):
        travel = 0.002 + 0.014 * (1.0 - quality)
        rock_amp = 0.0008 + 0.0100 * (1.0 - quality)
        for i in range(n):
            cx, y0 = 0.5, hip_y
            rock = rock_amp * math.sin(theta[i])
            kps = {
                "right_hip": Point(cx + 0.032, y0 + rock),
                "left_hip": Point(cx - 0.032, y0 - rock),
                "right_shoulder": Point(cx + 0.060, y0 - 0.150),
                "left_shoulder": Point(cx - 0.060, y0 - 0.150),
                "nose": Point(cx, y0 - 0.210),
                "right_ear": Point(cx + 0.022, y0 - 0.200),
                "left_ear": Point(cx - 0.022, y0 - 0.200),
            }
            for side, ph in (("right", theta[i]), ("left", theta[i] + math.pi)):
                sgn = 1 if side == "right" else -1
                kps[f"{side}_knee"] = Point(
                    cx + sgn * 0.030 + sgn * travel * math.sin(ph), y0 + 0.130
                )
                kps[f"{side}_ankle"] = Point(cx + sgn * 0.036, y0 + 0.235)
                kps[f"{side}_heel"] = Point(cx + sgn * 0.036, y0 + 0.252)
                kps[f"{side}_foot_index"] = Point(cx + sgn * 0.038, y0 + 0.268)
                kps[f"{side}_elbow"] = Point(cx + sgn * 0.070, y0 - 0.080)
                kps[f"{side}_wrist"] = Point(cx + sgn * 0.066, y0 - 0.030)
            if view is View.POSTERIOR:
                kps = _mirror_labels(kps)
            frames.append(_jitter(kps, rng, sigma, confidence, i))
    else:
        raise ValueError(f"gerador de ciclismo não cobre a vista {view.value}")

    return PoseSequence(
        frames=frames,
        view=view,
        fps=fps,
        source_id=f"synthetic:ciclismo:{view.value}:q{quality:.2f}",
        device={"backend": "synthetic", "quality": f"{quality:.2f}"},
    )


def _knee_forward(hip: Point, ankle: Point, femur: float, tibia: float) -> Point:
    from ..geometry import two_link_ik

    a = two_link_ik(hip, ankle, femur, tibia, flip=False)
    b = two_link_ik(hip, ankle, femur, tibia, flip=True)
    return a if a.x > b.x else b


# --------------------------------------------------------------------------- #
# Tiro com arco
# --------------------------------------------------------------------------- #


def archery(
    view: View = View.POSTERIOR,
    *,
    n_shots: int = 6,
    fps: float = 60.0,
    shot_s: float = 6.0,
    quality: float = 0.8,
    seed: int = 3,
    confidence: float = 0.85,
) -> PoseSequence:
    """Série de tiros. O que interessa aqui é a variação **entre** tiros."""
    if view is not View.POSTERIOR:
        raise ValueError("gerador de arco cobre apenas a vista posterior")

    rng = np.random.default_rng(seed)
    per_shot = int(round(shot_s * fps))
    frames: list[PoseFrame] = []

    # Variabilidade postural entre tiros: é isto que a métrica de
    # repetibilidade mede, e é o discriminante técnico do desporto.
    shot_sigma = 0.0035 + 0.0110 * (1.0 - quality)
    tremor = 0.0004 + 0.0035 * (1.0 - quality)

    for shot in range(n_shots):
        off = rng.normal(0.0, shot_sigma, 4)
        for k in range(per_shot):
            phase = k / per_shot
            # 0–35% preparação e tracção, 35–85% âncora e expansão, 85–95% largada.
            if phase < 0.35:
                drawn = min(1.0, max(0.0, (phase - 0.05) / 0.30))
            elif phase < 0.85:
                drawn = 1.0
            else:
                drawn = max(0.0, 1.0 - (phase - 0.85) / 0.10)
            aiming = 0.35 <= phase < 0.85
            shake = tremor if aiming else tremor * 0.35

            cx = 0.5
            hip_y = 0.560
            sh_y = 0.330 + off[0]
            kps = {
                "left_hip": Point(cx - 0.036, hip_y),
                "right_hip": Point(cx + 0.036, hip_y),
                # Ombro do arco (esquerdo) baixo é ponto técnico central:
                # quanto melhor a execução, mais baixo e mais estável fica.
                "left_shoulder": Point(
                    cx - 0.060 + off[1],
                    sh_y + (0.004 + 0.014 * (1.0 - quality)) * drawn,
                ),
                "right_shoulder": Point(cx + 0.060, sh_y + off[2]),
                "nose": Point(cx + 0.004, sh_y - 0.080),
                "left_ear": Point(cx - 0.022, sh_y - 0.086),
                "right_ear": Point(cx + 0.022, sh_y - 0.086),
                "left_ankle": Point(cx - 0.052, 0.880),
                "right_ankle": Point(cx + 0.052, 0.880),
                "left_knee": Point(cx - 0.044, 0.716),
                "right_knee": Point(cx + 0.044, 0.716),
                "left_heel": Point(cx - 0.054, 0.892),
                "right_heel": Point(cx + 0.054, 0.892),
                "left_foot_index": Point(cx - 0.050, 0.908),
                "right_foot_index": Point(cx + 0.050, 0.908),
            }
            # Braço do arco (esquerdo, atirador destro): estendido para a frente.
            kps["left_elbow"] = Point(cx - 0.140 * drawn - 0.020, sh_y + 0.014)
            kps["left_wrist"] = Point(cx - 0.215 * drawn - 0.020, sh_y + 0.020)
            # Braço de tracção: mão à face, o ponto de âncora.
            anchor_x = cx + 0.020 + off[3]
            kps["right_elbow"] = Point(cx + 0.150 * drawn, sh_y - 0.030 * drawn)
            kps["right_wrist"] = Point(anchor_x, sh_y - 0.062 * drawn)

            # Emula o que um detector de pose devolve numa vista posterior: o
            # modelo assume o sujeito virado para a câmara e troca os rótulos
            # esquerda/direita. É esta troca que `lateralityMapping: mirrored`
            # existe para corrigir — o gerador tem de a reproduzir, senão o
            # perfil ficaria a ser testado contra dados que já vinham certos.
            frames.append(_jitter(_mirror_labels(kps), rng, shake, confidence, len(frames)))

    return PoseSequence(
        frames=frames,
        view=view,
        fps=fps,
        source_id=f"synthetic:arco:{view.value}:q{quality:.2f}",
        device={"backend": "synthetic", "quality": f"{quality:.2f}", "shots": str(n_shots)},
    )


# --------------------------------------------------------------------------- #


def _mirror_labels(kps: dict[str, Point]) -> dict[str, Point]:
    """Troca os prefixos `left_`/`right_`, como faz um detector visto de trás."""
    out: dict[str, Point] = {}
    for name, p in kps.items():
        if name.startswith("left_"):
            out["right_" + name[5:]] = p
        elif name.startswith("right_"):
            out["left_" + name[6:]] = p
        else:
            out[name] = p
    return out


def _jitter(
    kps: dict[str, Point], rng: np.random.Generator, sigma: float, confidence: float, index: int
) -> PoseFrame:
    """Ruído de deteção e confiança variável, para que a filtragem tenha trabalho."""
    out: dict[str, Point] = {}
    for name, p in kps.items():
        # As extremidades são sistematicamente mais ruidosas — como no real.
        extra = 1.8 if ("foot" in name or "heel" in name or "wrist" in name) else 1.0
        conf = float(np.clip(rng.normal(confidence, 0.05), 0.0, 1.0))
        out[name] = Point(
            p.x + float(rng.normal(0, sigma * extra)),
            p.y + float(rng.normal(0, sigma * extra)),
            conf,
        )
    return PoseFrame(index=index, keypoints=out)
